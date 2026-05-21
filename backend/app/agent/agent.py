"""
Core agent loop — google-genai (Vertex AI) edition.

Architecture:
  1. Build initial user message with JD + pre-retrieved corpus context
  2. Call Gemini via Vertex AI with tool declarations + system instruction
  3. If response contains function_call parts → execute each tool → feed results back
  4. Repeat until response contains no function calls (natural end_turn)
  5. Return structured result
"""

import asyncio
import json
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import GENAI_TOOLS, execute_tool
from app.core.config import settings
from app.rag.retriever import retrieve


def _make_client() -> genai.Client:
    return genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
    )


async def _generate_with_retry(client, model, contents, config, max_attempts: int = 5):
    """Call generate_content with exponential backoff on 429 quota errors."""
    for attempt in range(max_attempts):
        try:
            return await client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except genai_errors.ClientError as exc:
            if getattr(exc, "code", None) != 429:
                raise
            if attempt == max_attempts - 1:
                raise
            match = re.search(r"seconds:\s*(\d+)", str(exc))
            wait = int(match.group(1)) if match else (2 ** attempt) * 10
            await asyncio.sleep(wait)


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
    client = _make_client()

    context: dict = {
        "db": db,
        "user_id": user_id,
        "job_description": job_description,
        "original_resume": None,
        "agent_steps": [],
    }

    # Seed the conversation with an initial retrieval using the full JD as the query.
    initial_chunks_text = ""
    try:
        initial_chunks = await retrieve(job_description, db, k=5)
        if initial_chunks:
            lines = ["Relevant career corpus chunks retrieved for this JD:\n"]
            for i, chunk in enumerate(initial_chunks, 1):
                meta = chunk.metadata or {}
                title = meta.get("title") or chunk.source_path.rsplit("/", 1)[-1]
                lines.append(
                    f"[{i}] {chunk.source_type}: {title} "
                    f"(chunk {chunk.chunk_index}, similarity {1 - chunk.distance:.2f})"
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
        context["agent_steps"].append(
            {"iteration": 0, "type": "rag_retrieval_error", "error": str(exc)}
        )

    gen_config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=GENAI_TOOLS,
        max_output_tokens=settings.agent_max_tokens,
    )

    messages: list[types.Content] = [
        types.Content(
            role="user",
            parts=[types.Part(text=_build_initial_message(job_description, user_id, initial_chunks_text))],
        )
    ]

    final_text = ""
    application_id: str | None = None

    for iteration in range(settings.agent_max_iterations):
        response = await _generate_with_retry(
            client,
            model=settings.agent_model,
            contents=messages,
            config=gen_config,
        )

        # Append the full model turn to history
        messages.append(response.candidates[0].content)

        # Collect function calls from this turn
        fn_calls = []
        for part in response.candidates[0].content.parts:
            fn_call = part.function_call
            if fn_call and fn_call.name:
                fn_calls.append(fn_call)
                context["agent_steps"].append(
                    {
                        "iteration": iteration + 1,
                        "type": "tool_call",
                        "tool": fn_call.name,
                        "input": dict(fn_call.args),
                    }
                )
            elif part.text and part.text.strip():
                context["agent_steps"].append(
                    {
                        "iteration": iteration + 1,
                        "type": "thought",
                        "text": part.text[:300],
                    }
                )

        # Natural completion — no function calls in this turn
        if not fn_calls:
            try:
                final_text = response.text or ""
            except Exception:
                text_parts = [p.text for p in response.candidates[0].content.parts if p.text]
                final_text = "\n".join(text_parts)
            break

        # Execute tools and build function response parts
        tool_parts = []
        for fn_call in fn_calls:
            tool_name = fn_call.name
            tool_args = dict(fn_call.args)

            result_text = await execute_tool(tool_name, tool_args, context)

            if tool_name == "save_application":
                try:
                    parsed = json.loads(result_text)
                    application_id = parsed.get("application_id")
                except (json.JSONDecodeError, AttributeError):
                    pass

            context["agent_steps"].append(
                {
                    "iteration": iteration + 1,
                    "type": "tool_result",
                    "tool": tool_name,
                    "result_preview": result_text[:400] + ("…" if len(result_text) > 400 else ""),
                }
            )

            tool_parts.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response={"output": result_text},
                )
            )

        messages.append(types.Content(role="user", parts=tool_parts))

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
**Initial corpus retrieval** (broad JD query — 5 most relevant chunks):
---
{initial_context}
---
This is a starting point. Call `list_corpus_sources` to see the full career inventory, \
then use `retrieve_relevant_experience` for targeted follow-up queries.

"""

    return f"""Please help me tailor my job application for the following position.

**My User ID**: {user_id}

**Job Description**:
---
{job_description}
---
{context_section}
Follow the strategy in your system prompt:
1. Explore my career corpus (`list_corpus_sources`, then targeted `retrieve_relevant_experience` calls)
2. Read my current resume to see what I already present to employers
3. Research the company (culture, tech stack, recent news)
4. Identify skill gaps and keyword matches
5. Rewrite the 3-5 most impactful resume bullets
6. Surface hidden gems — corpus items not on my resume that are relevant to this role
7. Draft a tailored cover letter for this specific company and position
8. Save the complete analysis
9. Give me an honest, actionable summary

Be specific. I want to know exactly what to highlight, what to add, and what to work on."""
