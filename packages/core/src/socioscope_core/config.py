from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    llm_model: str = Field(default="claude-opus-5-5", alias="SOCIOSCOPE_LLM_MODEL")
    data_dir: Path = Field(default=Path("data"), alias="SOCIOSCOPE_DATA_DIR")
    user_agent: str = Field(
        default="socioscope/0.1 (+https://github.com/; research; contact via repo issues)",
        alias="SOCIOSCOPE_USER_AGENT",
    )

    def __repr__(self) -> str:  # never leak the key
        return f"Settings(llm_model={self.llm_model!r}, data_dir={str(self.data_dir)!r})"
