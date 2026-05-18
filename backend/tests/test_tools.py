import pytest

from app.agent.tools import TOOL_DEFINITIONS, execute_tool


# ---------------------------------------------------------------------------
# Tool registration checks
# ---------------------------------------------------------------------------


def test_retrieve_tool_is_registered():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert "retrieve_relevant_experience" in names


def test_retrieve_tool_comes_before_save_application():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert names.index("retrieve_relevant_experience") < names.index("save_application")


def test_save_application_still_has_cache_control():
    save_tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "save_application")
    assert "cache_control" in save_tool
    assert save_tool["cache_control"]["type"] == "ephemeral"


def test_retrieve_tool_schema_has_required_fields():
    tool = next(t for t in TOOL_DEFINITIONS if t["name"] == "retrieve_relevant_experience")
    props = tool["input_schema"]["properties"]
    required = tool["input_schema"]["required"]
    assert "query" in props
    assert "k" in props
    assert "source_types" in props
    assert "query" in required
    # k and source_types are optional
    assert "k" not in required
    assert "source_types" not in required


def test_no_duplicate_tool_names():
    names = [t["name"] for t in TOOL_DEFINITIONS]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_returns_error_string():
    result = await execute_tool("does_not_exist", {}, {})
    assert "Unknown tool" in result
    assert "does_not_exist" in result
