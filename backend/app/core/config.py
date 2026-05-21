from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project: str
    gcp_location: str = "us-central1"
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/jobagent"
    resume_dir: str = "/app/resumes"

    # Agent config
    agent_model: str = "gemini-2.5-flash"
    agent_max_tokens: int = 8192
    agent_max_iterations: int = 20


settings = Settings()
