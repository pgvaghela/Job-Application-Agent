import uuid
from datetime import datetime

from pydantic import BaseModel


class RewrittenBullet(BaseModel):
    original: str
    rewritten: str
    reason: str


class AnalyzeRequest(BaseModel):
    job_description: str
    user_id: str = "default"


class AnalyzeResponse(BaseModel):
    application_id: uuid.UUID
    summary: str
    agent_steps: list[dict]


class ApplicationDetail(BaseModel):
    id: uuid.UUID
    user_id: str
    created_at: datetime
    job_title: str
    company_name: str
    job_description: str
    company_info: str | None
    skill_gaps: list[str]
    keyword_matches: list[str]
    match_score: int | None
    original_resume: str | None
    rewritten_bullets: list[dict]
    cover_letter: str | None
    agent_steps: list[dict]
    has_pdf: bool = False

    @classmethod
    def model_validate(cls, obj, **kwargs):
        instance = super().model_validate(obj, **kwargs)
        instance.has_pdf = bool(getattr(obj, "modified_resume_tex", None))
        return instance

    model_config = {"from_attributes": True}


class ApplicationSummary(BaseModel):
    id: uuid.UUID
    created_at: datetime
    job_title: str
    company_name: str
    match_score: int | None

    model_config = {"from_attributes": True}


class ResumeContent(BaseModel):
    content: str
