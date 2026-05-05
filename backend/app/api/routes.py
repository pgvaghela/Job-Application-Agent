import subprocess
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent import run_agent
from app.agent.latex import generate_modified_tex
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Application, Resume
from app.db.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    ApplicationDetail,
    ApplicationSummary,
    ResumeContent,
)

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_job(
    body: AnalyzeRequest,
    db: AsyncSession = Depends(get_db),
) -> AnalyzeResponse:
    if len(body.job_description.strip()) < 50:
        raise HTTPException(status_code=400, detail="Job description is too short.")

    result = await run_agent(
        job_description=body.job_description,
        user_id=body.user_id,
        db=db,
    )

    if result.application_id is None:
        raise HTTPException(
            status_code=500,
            detail="Agent completed but did not save an application. Check logs.",
        )

    # If the original resume was LaTeX, generate modified .tex with rewritten bullets
    app = await db.get(Application, uuid.UUID(result.application_id))
    if app and app.original_resume and "(format: tex)" in app.original_resume[:120]:
        try:
            # Strip the "Resume for user '...' (format: tex):\n\n" header
            tex_content = app.original_resume.split("\n\n", 1)[1]
            modified = await generate_modified_tex(tex_content, app.rewritten_bullets)
            app.modified_resume_tex = modified
            await db.flush()
        except Exception as exc:
            # PDF generation is a bonus feature — don't fail the whole request
            print(f"[latex] Failed to generate modified tex: {exc}")

    return AnalyzeResponse(
        application_id=uuid.UUID(result.application_id),
        summary=result.summary,
        agent_steps=result.agent_steps,
    )


@router.get("/applications", response_model=list[ApplicationSummary])
async def list_applications(
    user_id: str = "default",
    db: AsyncSession = Depends(get_db),
) -> list[ApplicationSummary]:
    stmt = (
        select(Application)
        .where(Application.user_id == user_id)
        .order_by(Application.created_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [ApplicationSummary.model_validate(r) for r in rows]


@router.get("/applications/{application_id}/resume.pdf")
async def download_resume_pdf(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Compile the modified LaTeX resume to PDF and stream it back."""
    app = await db.get(Application, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found.")
    if not app.modified_resume_tex:
        raise HTTPException(
            status_code=404,
            detail="No modified LaTeX available. Upload a .tex resume and run the agent.",
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = Path(tmpdir) / "resume.tex"
        tex_path.write_text(app.modified_resume_tex, encoding="utf-8")

        # Run pdflatex twice — second pass resolves hyperlinks and references
        for _ in range(2):
            proc = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "resume.tex"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=60,
            )

        pdf_path = Path(tmpdir) / "resume.pdf"
        if not pdf_path.exists():
            log = proc.stdout[-2000:] + proc.stderr[-500:]
            raise HTTPException(
                status_code=500,
                detail=f"PDF compilation failed. pdflatex output:\n{log}",
            )

        return Response(
            content=pdf_path.read_bytes(),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="resume_{application_id}.pdf"'
            },
        )


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
async def get_application(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ApplicationDetail:
    row = await db.get(Application, application_id)
    if not row:
        raise HTTPException(status_code=404, detail="Application not found.")
    return ApplicationDetail.model_validate(row)


@router.get("/resume/{user_id}", response_model=ResumeContent)
async def get_resume(user_id: str) -> ResumeContent:
    path = Path(settings.resume_dir) / f"{user_id}.md"
    if not path.exists():
        path = Path(settings.resume_dir) / "default.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="No resume found for this user.")
    return ResumeContent(content=path.read_text())


@router.post("/resume/{user_id}", response_model=ResumeContent)
async def update_resume(user_id: str, body: ResumeContent) -> ResumeContent:
    resume_dir = Path(settings.resume_dir)
    resume_dir.mkdir(parents=True, exist_ok=True)
    path = resume_dir / f"{user_id}.md"
    path.write_text(body.content)
    return ResumeContent(content=body.content)


@router.post("/resume/{user_id}/upload", response_model=ResumeContent)
async def upload_resume(
    user_id: str,
    file: UploadFile = File(...),
) -> ResumeContent:
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in {".tex", ".md", ".txt"}:
        raise HTTPException(
            status_code=400,
            detail="Only .tex, .md, or .txt files are supported.",
        )

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    resume_dir = Path(settings.resume_dir)
    resume_dir.mkdir(parents=True, exist_ok=True)

    save_path = resume_dir / f"{user_id}{ext}"
    save_path.write_text(text, encoding="utf-8")

    for other_ext in {".tex", ".md", ".txt"} - {ext}:
        stale = resume_dir / f"{user_id}{other_ext}"
        if stale.exists():
            stale.unlink()

    return ResumeContent(content=text)
