"""
Single-turn Vertex AI call that substitutes rewritten bullets back into the
original LaTeX source. Not part of the agentic loop — runs after the agent
completes, only when the uploaded resume was a .tex file.
"""

from google import genai
from google.genai import types

from app.core.config import settings


def _braces_balanced(tex: str) -> bool:
    depth = 0
    for ch in tex:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth < 0:
            return False
    return depth == 0


async def generate_modified_tex(original_tex: str, rewritten_bullets: list[dict]) -> str:
    """
    Takes the original LaTeX resume and the agent's rewritten bullets,
    returns a modified LaTeX with the bullets substituted in-place.
    """
    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_location,
    )

    bullets_block = "\n\n".join(
        f"ORIGINAL TEXT (the text inside the LaTeX command, not the command itself):\n{b['original']}\n\n"
        f"REPLACEMENT TEXT:\n{b['rewritten']}"
        for b in rewritten_bullets
    )

    prompt = f"""You will modify a LaTeX resume by substituting rewritten bullet text.

CRITICAL RULES — violations will break the PDF:
1. Only change the human-readable text of the bullets. Never add, remove, or move any LaTeX commands, braces, brackets, or special characters.
2. If a bullet uses \\resumeItem{{text here}}, you keep \\resumeItem{{ and }} and only replace "text here".
3. If a bullet uses \\item text here, you keep \\item and only replace "text here".
4. Every opening brace {{ must have a matching closing brace }}.
5. Never truncate a bullet mid-sentence — write the complete replacement text.
6. Match bullets by meaning — the ORIGINAL TEXT may be slightly paraphrased, find the closest match.
7. If you cannot confidently match a bullet, leave that line completely unchanged.
8. Return ONLY the complete LaTeX source. No explanation, no markdown code fences.

ORIGINAL LATEX:
{original_tex}

BULLETS TO SUBSTITUTE:
{bullets_block}"""

    response = await client.aio.models.generate_content(
        model=settings.agent_model,
        contents=prompt,
        config=types.GenerateContentConfig(max_output_tokens=8192),
    )

    result = response.text.strip()

    # Strip markdown fences if the model wrapped the output anyway
    if result.startswith("```"):
        lines = result.split("\n")
        result = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    if not _braces_balanced(result):
        raise ValueError("Generated LaTeX has unbalanced braces — refusing to store.")

    return result
