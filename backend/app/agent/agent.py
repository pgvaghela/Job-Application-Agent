"""
Core agent loop.

Architecture:
  1. Build initial user message with JD + instructions
  2. Call Claude (claude-opus-4-7) with tool definitions + system prompt
  3. If Claude returns tool_use blocks → execute each tool → feed results back
  4. Repeat until stop_reason == "end_turn"
  5. Return structured result

Prompt caching:
  - System prompt has cache_control → caches the system block
  - Last tool definition has cache_control → caches the entire tools prefix
  - Both are stable across iterations, so every tool-execution turn hits the cache
"""

import json
from dataclasses import dataclass, field

import anthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOL_DEFINITIONS, execute_tool
from app.core.config import settings
from app.rag.retriever import retrieve


@dataclass
class AgentResult:
    application_id: str | None
    summary: str
    agent_steps: list[dict] = field(default_factory=list)


async def run_agent(
    job_description: str,
    user_id: str,
    db: AsyncSession,
) -> AgentResult:
    """
    Run the job application agent.
    Returns a structured result after the agent finishes its reasoning loop.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Context shared across tool calls within this session
    context: dict = {
        "db": db,
        "user_id": user_id,
        "job_description": job_description,
        "original_resume": None,
        "agent_steps": [],
    }

    # Seed the conversation with an initial retrieval using the full JD as the query.
    # This surfaces the most relevant experience before Claude makes a single tool call,
    # keeping the system prompt cache clean (no dynamic content there).
    initial_chunks_text = ""
    try:
        initial_chunks = await retrieve(job_description, db, k=5)
        if initial_chunks:
            lines = ["Relevant experience retrieved from your corpus:\n"]
            for i, chunk in enumerate(initial_chunks, 1):
                source_name = chunk.source_path.rsplit("/", 1)[-1]
                lines.append(
                    f"[{i}] {chunk.source_type}/{source_name} "
                    f"(chunk {chunk.chunk_index}, distance {chunk.distance:.3f})"
                )
                lines.append(chunk.content)
                lines.append("")
            initial_chunks_text = "\n".join(lines)
            context["agent_steps"].append(
                {
                    "iteration": 0,
                    "type": "rag_retrieval",
                    "query": "[initial — full JD]",
                    "k": 5,
                    "source_types": None,
                    "chunks_returned": [
                        {
                            "source_type": c.source_type,
                            "source_path": c.source_path,
                            "chunk_index": c.chunk_index,
                            "distance": round(c.distance, 4),
                        }
                        for c in initial_chunks
                    ],
                }
            )
    except Exception as exc:
        # Corpus may be empty or Gemini key not set — degrade gracefully.
        context["agent_steps"].append(
            {"iteration": 0, "type": "rag_retrieval_error", "error": str(exc)}
        )

    # System prompt with cache_control so it (and the tools prefix) is cached
    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    messages = [
        {
            "role": "user",
            "content": _build_initial_message(job_description, user_id, initial_chunks_text),
        }
    ]

    final_text = ""
    application_id: str | None = None

    for iteration in range(settings.agent_max_iterations):
        response = await client.messages.create(
            model=settings.agent_model,
            max_tokens=settings.agent_max_tokens,
            thinking={"type": "adaptive"},
            system=system,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Append the full assistant response (preserves tool_use + thinking blocks)
        messages.append({"role": "assistant", "content": response.content})

        # Log each content block for the UI
        for block in response.content:
            if block.type == "tool_use":
                step = {
                    "iteration": iteration + 1,
                    "type": "tool_call",
                    "tool": block.name,
                    "input": block.input,
                }
                context["agent_steps"].append(step)
            elif block.type == "text" and block.text.strip():
                context["agent_steps"].append(
                    {
                        "iteration": iteration + 1,
                        "type": "thought",
                        "text": block.text[:300],  # truncate for storage
                    }
                )

        # ── Natural completion ──────────────────────────────────────────────
        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    final_text += block.text
            break

        # ── Tool use ────────────────────────────────────────────────────────
        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                result_text = await execute_tool(block.name, block.input, context)

                # Extract application_id if this was the save call
                if block.name == "save_application":
                    try:
                        parsed = json.loads(result_text)
                        application_id = parsed.get("application_id")
                    except (json.JSONDecodeError, AttributeError):
                        pass

                context["agent_steps"].append(
                    {
                        "iteration": iteration + 1,
                        "type": "tool_result",
                        "tool": block.name,
                        # Truncate long results (resume text, search results) for the log
                        "result_preview": result_text[:400] + ("…" if len(result_text) > 400 else ""),
                    }
                )

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason — break to avoid infinite loop
        break

    return AgentResult(
        application_id=application_id,
        summary=final_text or "Analysis complete. Check the results panel for details.",
        agent_steps=context["agent_steps"],
    )


def _build_initial_message(
    job_description: str,
    user_id: str,
    initial_context: str = "",
) -> str:
    context_section = ""
    if initial_context:
        context_section = f"""
**Pre-retrieved Relevant Experience**:
---
{initial_context}
---
The above was retrieved semantically from your corpus. Use `retrieve_relevant_experience` \
for targeted follow-up queries on specific skills or domains.

"""

    return f"""Please help me tailor my job application for the following position.

**My User ID**: {user_id}

**Job Description**:
---
{job_description}
---
{context_section}
Please:
1. Research this company thoroughly (culture, tech stack, recent news)
2. Analyze the JD against my background — identify skill gaps and keyword matches
3. Use `retrieve_relevant_experience` for any specific skills or domains you need more evidence on
4. Rewrite the 3-5 most relevant resume bullets to better align with this role
5. Draft a tailored cover letter for this specific company and position
6. Save the complete analysis to the database
7. Give me an honest summary with your top recommendations

Be specific and actionable. I want to know exactly what to highlight and what to work on."""
