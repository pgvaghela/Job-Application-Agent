"""
Tool implementations and definitions for the job application agent.

Each tool is:
  - Defined in TOOL_DEFINITIONS (sent to Claude so it knows what's available)
  - Implemented as an async Python function
  - Dispatched through execute_tool()
"""

import asyncio
import json
import os
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Application

# ---------------------------------------------------------------------------
# Tool schemas — sent to Claude with cache_control on the last one so that
# the entire tools + system prompt prefix is cached across agent iterations.
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "read_resume",
        "description": (
            "Read the candidate's full resume from disk. "
            "Use this as a fallback when you need the complete resume text. "
            "For most queries, prefer retrieve_relevant_experience which returns "
            "semantically relevant chunks instead of the whole document."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The user's ID. Use 'default' if not specified.",
                }
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "search_web",
        "description": (
            "Search the web for up-to-date information about a company, "
            "technology, or topic relevant to the job application. "
            "Use this to research company culture, tech stack, recent news, "
            "and mission. Run 2-3 searches for thorough coverage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-10). Default 5.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "retrieve_relevant_experience",
        "description": (
            "Fetch the most relevant resume bullets, project details, or writing samples "
            "for a given query. Use this when you need specific evidence of experience with "
            "a skill, technology, or domain mentioned in the job description. "
            "Initial relevant context is already pre-seeded in your first message, but "
            "call this tool for targeted sub-queries as needed — e.g., 'Python backend "
            "projects', 'leadership examples', 'distributed systems experience'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to look for. Be specific: 'machine learning experience', "
                        "'open source contributions', 'team leadership examples'."
                    ),
                },
                "k": {
                    "type": "integer",
                    "description": "Number of chunks to return (1-10). Default 5.",
                    "default": 5,
                },
                "source_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional filter: 'resume', 'readme', 'writing_sample'. "
                        "Omit to search all sources."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "save_application",
        "description": (
            "Save the complete job application analysis to the database. "
            "Call this AFTER you have read the resume, researched the company, "
            "analyzed skill gaps, rewritten bullets, and drafted a cover letter. "
            "This is the final tool call before giving your summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_title": {
                    "type": "string",
                    "description": "The job title from the job description.",
                },
                "company_name": {
                    "type": "string",
                    "description": "The company name from the job description.",
                },
                "company_info": {
                    "type": "string",
                    "description": (
                        "Summary of your company research: culture, tech stack, "
                        "recent news, and mission. 2-4 paragraphs."
                    ),
                },
                "skill_gaps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Skills explicitly required in the JD that are missing "
                        "or weak in the resume."
                    ),
                },
                "keyword_matches": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Technical skills, tools, and methodologies that appear "
                        "in both the JD and the resume."
                    ),
                },
                "rewritten_bullets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "original": {
                                "type": "string",
                                "description": "The original resume bullet.",
                            },
                            "rewritten": {
                                "type": "string",
                                "description": "The improved bullet that better matches the JD.",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Why this rewrite improves alignment with the JD.",
                            },
                        },
                        "required": ["original", "rewritten", "reason"],
                    },
                    "description": (
                        "The 3-5 most impactful resume bullets, rewritten to "
                        "better align with this JD. Only include bullets that "
                        "were actually changed. Never fabricate experience."
                    ),
                },
                "cover_letter": {
                    "type": "string",
                    "description": (
                        "A complete, tailored cover letter (3-4 paragraphs) "
                        "specific to this company and role."
                    ),
                },
                "match_score": {
                    "type": "integer",
                    "description": (
                        "Estimated match percentage (0-100) between the candidate "
                        "and this job. Be honest and calibrated."
                    ),
                },
            },
            "required": [
                "job_title",
                "company_name",
                "skill_gaps",
                "keyword_matches",
                "rewritten_bullets",
                "cover_letter",
                "match_score",
            ],
        },
        # Prompt cache breakpoint: caches tools + system prefix across iterations.
        "cache_control": {"type": "ephemeral"},
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def tool_read_resume(user_id: str) -> str:
    resume_dir = Path(settings.resume_dir)
    candidates = [
        resume_dir / f"{user_id}.tex",
        resume_dir / f"{user_id}.md",
        resume_dir / f"{user_id}.txt",
        resume_dir / "default.tex",
        resume_dir / "default.md",
    ]
    resume_path = next((p for p in candidates if p.exists()), None)
    if resume_path is None:
        return "Error: No resume found. Please upload your resume first."

    content = resume_path.read_text(encoding="utf-8")
    fmt = resume_path.suffix.lstrip(".")
    return f"Resume for user '{user_id}' (format: {fmt}):\n\n{content}"


async def tool_search_web(query: str, max_results: int = 5) -> str:
    def _sync_search() -> list[dict]:
        try:
            from duckduckgo_search import DDGS

            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except Exception as exc:
            return [{"title": "Search error", "href": "", "body": str(exc)}]

    results = await asyncio.get_event_loop().run_in_executor(None, _sync_search)

    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r.get('title', 'No title')}**")
        lines.append(f"   URL: {r.get('href', '')}")
        lines.append(f"   {r.get('body', '')}\n")

    return "\n".join(lines)


async def tool_retrieve_relevant_experience(tool_input: dict, context: dict) -> str:
    from app.rag.retriever import retrieve

    query: str = tool_input["query"]
    k: int = min(int(tool_input.get("k", 5)), 10)
    source_types: list[str] | None = tool_input.get("source_types") or None

    chunks = await retrieve(query, context["db"], k=k, source_types=source_types)

    context["agent_steps"].append(
        {
            "type": "rag_retrieval",
            "query": query,
            "k": k,
            "source_types": source_types,
            "chunks_returned": [
                {
                    "source_type": c.source_type,
                    "source_path": c.source_path,
                    "chunk_index": c.chunk_index,
                    "distance": round(c.distance, 4),
                }
                for c in chunks
            ],
        }
    )

    if not chunks:
        return f"No relevant experience found for query: {query!r}"

    lines = [f"Retrieved {len(chunks)} chunk(s) for: {query!r}\n"]
    for i, chunk in enumerate(chunks, 1):
        source_name = chunk.source_path.rsplit("/", 1)[-1]
        lines.append(
            f"[{i}] {chunk.source_type}/{source_name} "
            f"(chunk {chunk.chunk_index}, distance {chunk.distance:.3f})"
        )
        lines.append(chunk.content)
        lines.append("")

    return "\n".join(lines)


async def tool_save_application(tool_input: dict, context: dict) -> str:
    db: AsyncSession = context["db"]

    application = Application(
        id=uuid.uuid4(),
        user_id=context["user_id"],
        job_description=context["job_description"],
        original_resume=context.get("original_resume", ""),
        job_title=tool_input["job_title"],
        company_name=tool_input["company_name"],
        company_info=tool_input.get("company_info", ""),
        skill_gaps=tool_input["skill_gaps"],
        keyword_matches=tool_input["keyword_matches"],
        rewritten_bullets=tool_input["rewritten_bullets"],
        cover_letter=tool_input["cover_letter"],
        match_score=tool_input["match_score"],
        agent_steps=context.get("agent_steps", []),
    )

    db.add(application)
    await db.flush()  # get the ID without committing; route commits after success

    return json.dumps(
        {
            "application_id": str(application.id),
            "status": "saved",
            "job_title": application.job_title,
            "company_name": application.company_name,
        }
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def execute_tool(tool_name: str, tool_input: dict, context: dict) -> str:
    """
    Route a tool call to its implementation.
    context holds: db, user_id, job_description, original_resume, agent_steps.
    """
    try:
        if tool_name == "read_resume":
            result = await tool_read_resume(tool_input["user_id"])
            # Stash resume text so save_application can persist it
            context["original_resume"] = result
            return result

        elif tool_name == "search_web":
            return await tool_search_web(
                tool_input["query"],
                tool_input.get("max_results", 5),
            )

        elif tool_name == "retrieve_relevant_experience":
            return await tool_retrieve_relevant_experience(tool_input, context)

        elif tool_name == "save_application":
            return await tool_save_application(tool_input, context)

        else:
            return f"Error: Unknown tool '{tool_name}'"

    except Exception as exc:
        return f"Tool error in '{tool_name}': {exc}"
