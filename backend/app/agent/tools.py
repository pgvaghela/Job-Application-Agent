"""
Tool implementations and definitions for the job application agent.

Each tool is:
  - Defined in TOOL_DEFINITIONS (Anthropic-style schema, for reference)
  - GEMINI_TOOLS is derived from it — same content, Gemini-compatible format
  - Implemented as an async Python function
  - Dispatched through execute_tool()
"""

import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Application

# ---------------------------------------------------------------------------
# Tool schemas (Anthropic-style input_schema; GEMINI_TOOLS is derived below)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "list_corpus_sources",
        "description": (
            "List all documents in the candidate's career corpus so you know what's "
            "available before making targeted retrieval queries. Returns a structured "
            "inventory: source type, title, company, date range, and tags for each document. "
            "Call this first to understand the full scope of the candidate's career history, "
            "then use retrieve_relevant_experience for targeted queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional filter: 'experience', 'project', 'achievement', 'writing_sample'. "
                        "Omit to list all documents."
                    ),
                }
            },
        },
    },
    {
        "name": "read_resume",
        "description": (
            "Read the candidate's current resume from disk. "
            "The resume is their curated 1-2 page document — a subset of their full career history. "
            "Use this to see what they currently present to employers. "
            "For discovering additional relevant experience, use retrieve_relevant_experience."
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
            "Semantic search over the candidate's full career corpus — every project, role, "
            "achievement, and writing sample they've documented. The corpus may contain far more "
            "experience than what's on their current resume. Use this to discover relevant "
            "experience for specific skills or domains required by the job. "
            "Initial context is pre-seeded in your first message, but call this for targeted "
            "sub-queries: 'Python backend architecture', 'team leadership examples', "
            "'distributed systems work', 'open source contributions'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "What to look for. Be specific: 'machine learning pipelines', "
                        "'cross-functional leadership', 'cloud infrastructure projects'."
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
                        "Optional filter: 'experience', 'project', 'achievement', 'writing_sample'. "
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
            "Call this AFTER you have reviewed the resume, explored the corpus, researched "
            "the company, analyzed skill gaps, rewritten bullets, and drafted a cover letter. "
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
                        "or weak in the candidate's known background."
                    ),
                },
                "keyword_matches": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Technical skills, tools, and methodologies that appear "
                        "in both the JD and the candidate's background."
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
                "suggested_additions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Short title of the experience (e.g. 'Billing System Migration').",
                            },
                            "source_type": {
                                "type": "string",
                                "description": "Type: 'experience', 'project', 'achievement', or 'writing_sample'.",
                            },
                            "text": {
                                "type": "string",
                                "description": (
                                    "A concise, resume-ready bullet or summary drawn from the corpus item. "
                                    "Write it as if it could be dropped onto the resume."
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": "Why this corpus item is specifically relevant to this job.",
                            },
                        },
                        "required": ["title", "source_type", "text", "reason"],
                    },
                    "description": (
                        "Corpus items that are NOT currently on the resume but are highly relevant "
                        "to this role. These are hidden gems the candidate should consider adding. "
                        "Include 2-5 items maximum. Only include items you actually found in the corpus — "
                        "never fabricate. Leave empty if the resume already covers all relevant experience."
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
                "suggested_additions",
            ],
        },
    },
]

# Vertex AI's Schema proto doesn't support "default" or "additionalProperties".
# Strip them recursively before building tool declarations.
def _clean_schema(schema: dict) -> dict:
    unsupported = {"default", "additionalProperties"}
    result = {k: v for k, v in schema.items() if k not in unsupported}
    if "properties" in result:
        result["properties"] = {k: _clean_schema(v) for k, v in result["properties"].items()}
    if "items" in result and isinstance(result["items"], dict):
        result["items"] = _clean_schema(result["items"])
    return result


def _dict_to_schema(d: dict):
    from google.genai import types

    type_map = {
        "object": "OBJECT", "string": "STRING", "integer": "INTEGER",
        "number": "NUMBER", "boolean": "BOOLEAN", "array": "ARRAY",
    }
    kwargs: dict = {}
    kwargs["type"] = type_map.get((d.get("type") or "string").lower(), "STRING")
    if "description" in d:
        kwargs["description"] = d["description"]
    if "properties" in d:
        kwargs["properties"] = {k: _dict_to_schema(v) for k, v in d["properties"].items()}
    if "required" in d:
        kwargs["required"] = d["required"]
    if "items" in d and isinstance(d["items"], dict):
        kwargs["items"] = _dict_to_schema(d["items"])
    if "enum" in d:
        kwargs["enum"] = d["enum"]
    return types.Schema(**kwargs)


def _make_genai_tools():
    from google.genai import types

    declarations = []
    for t in TOOL_DEFINITIONS:
        kwargs: dict = {"name": t["name"], "description": t["description"]}
        if "input_schema" in t:
            kwargs["parameters"] = _dict_to_schema(_clean_schema(t["input_schema"]))
        declarations.append(types.FunctionDeclaration(**kwargs))
    return [types.Tool(function_declarations=declarations)]


GENAI_TOOLS = _make_genai_tools()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def tool_list_corpus_sources(tool_input: dict, context: dict) -> str:
    from sqlalchemy import select

    from app.db.models import CorpusDocument

    db: AsyncSession = context["db"]
    source_types: list[str] | None = tool_input.get("source_types") or None

    stmt = select(CorpusDocument).order_by(
        CorpusDocument.source_type, CorpusDocument.created_at
    )
    if source_types:
        stmt = stmt.where(CorpusDocument.source_type.in_(source_types))

    result = await db.execute(stmt)
    docs = result.scalars().all()

    if not docs:
        return (
            "The career corpus is empty — no documents have been ingested yet. "
            "The candidate should run the ingest script to populate their career history."
        )

    lines = [f"Career corpus: {len(docs)} document(s)\n"]
    current_type: str | None = None
    for doc in docs:
        if doc.source_type != current_type:
            current_type = doc.source_type
            lines.append(f"[{current_type.upper()}]")

        meta = doc.metadata_ or {}
        title = meta.get("title") or doc.source_path.rsplit("/", 1)[-1]
        company = meta.get("company", "")
        date_range = meta.get("date_range", "")
        tags: list[str] = meta.get("tags") or []

        entry = f"  • {title}"
        if company:
            entry += f" @ {company}"
        if date_range:
            entry += f" ({date_range})"
        if tags:
            entry += f" — {', '.join(str(t) for t in tags)}"
        lines.append(entry)

    return "\n".join(lines)


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
        meta = chunk.metadata or {}
        title = meta.get("title") or chunk.source_path.rsplit("/", 1)[-1]
        company = meta.get("company", "")
        date_range = meta.get("date_range", "")
        tags: list[str] = meta.get("tags") or []

        header = f"[{i}] {chunk.source_type}: {title}"
        if company:
            header += f" @ {company}"
        if date_range:
            header += f" ({date_range})"
        if tags:
            header += f" | tags: {', '.join(str(t) for t in tags)}"
        header += f" [chunk {chunk.chunk_index}, similarity {1 - chunk.distance:.2f}]"

        lines.append(header)
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
        suggested_additions=tool_input.get("suggested_additions", []),
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
        if tool_name == "list_corpus_sources":
            return await tool_list_corpus_sources(tool_input, context)

        elif tool_name == "read_resume":
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
