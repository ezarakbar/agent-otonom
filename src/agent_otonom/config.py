"""Application configuration loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_root() -> Path:
    # src/agent_otonom/config.py → repo root is parents[2]
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    agent_host: str = Field(default="127.0.0.1", alias="AGENT_HOST")
    agent_port: int = Field(default=8790, alias="AGENT_PORT")
    agent_root: Path = Field(default_factory=_default_root, alias="AGENT_ROOT")

    ollama_base_url: str = Field(default="http://127.0.0.1:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5:3b", alias="OLLAMA_MODEL")

    sovits_base_url: str = Field(default="http://127.0.0.1:9880", alias="SOVITS_BASE_URL")
    sovits_ref_audio: str = Field(default="", alias="SOVITS_REF_AUDIO")
    sovits_prompt_text: str = Field(default="", alias="SOVITS_PROMPT_TEXT")
    sovits_prompt_lang: str = Field(default="auto", alias="SOVITS_PROMPT_LANG")

    comfyui_base_url: str = Field(default="http://127.0.0.1:8188", alias="COMFYUI_BASE_URL")
    comfy_checkpoint: str = Field(default="", alias="COMFY_CHECKPOINT")

    # ComfyUI + GPT-SoVITS are primary media engines. Piper/espeak/slideshow
    # only run when this is true.
    allow_engine_fallback: bool = Field(default=False, alias="ALLOW_ENGINE_FALLBACK")

    piper_bin: str = Field(default="", alias="PIPER_BIN")
    piper_model: str = Field(default="", alias="PIPER_MODEL")

    worker_concurrency: int = Field(default=1, alias="WORKER_CONCURRENCY")
    job_timeout_sec: int = Field(default=7200, alias="JOB_TIMEOUT_SEC")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    allow_dynamic_workflows: bool = Field(default=True, alias="ALLOW_DYNAMIC_WORKFLOWS")
    require_confirm_new_workflow: bool = Field(
        default=True, alias="REQUIRE_CONFIRM_NEW_WORKFLOW"
    )
    require_production_brief: bool = Field(
        default=True, alias="REQUIRE_PRODUCTION_BRIEF"
    )
    # When true: still builds professional brief, then auto-runs recommended option
    auto_execute_production: bool = Field(default=True, alias="AUTO_EXECUTE_PRODUCTION")
    enable_web_research: bool = Field(default=True, alias="ENABLE_WEB_RESEARCH")
    lipsync_base_url: str = Field(default="", alias="LIPSYNC_BASE_URL")

    @property
    def outputs_dir(self) -> Path:
        return self.agent_root / "outputs"

    @property
    def jobs_dir(self) -> Path:
        return self.agent_root / "jobs"

    @property
    def logs_dir(self) -> Path:
        return self.agent_root / "logs"

    @property
    def uploads_dir(self) -> Path:
        return self.agent_root / "uploads"

    @property
    def workflows_dir(self) -> Path:
        return self.agent_root / "workflows"

    @property
    def web_dir(self) -> Path:
        return self.agent_root / "web"

    @property
    def db_path(self) -> Path:
        return self.jobs_dir / "agent.db"

    def ensure_dirs(self) -> None:
        for d in (
            self.outputs_dir,
            self.jobs_dir,
            self.logs_dir,
            self.uploads_dir,
            self.workflows_dir,
            self.workflows_dir / "_generated",
            self.agent_root / "models" / "sovits",
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    root = settings.agent_root
    # Empty AGENT_ROOT= in .env must not win over repo root
    if root is None or str(root).strip() in {"", ".", "None"}:
        settings = settings.model_copy(update={"agent_root": _default_root()})
    else:
        settings = settings.model_copy(update={"agent_root": Path(root).expanduser().resolve()})
    settings.ensure_dirs()
    return settings
