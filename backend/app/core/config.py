from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str
    gemini_api_key: str = ""
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/jobagent"
    resume_dir: str = "/app/resumes"

    # Agent config
    agent_model: str = "claude-opus-4-7"
    agent_max_tokens: int = 8192
    agent_max_iterations: int = 20


settings = Settings()
