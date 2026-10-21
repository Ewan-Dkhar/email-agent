"""
Configuration Management Module.
Implements hierarchical configuration loading:
Default Values -> config.yaml -> Environment Variable Overrides.
"""

from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class DatabaseConfig(BaseModel):
    path: str = "agent_vault.db"

    def resolved_path(self, base_dir: Path) -> Path:
        """Resolves database path relative to backend root unless absolute."""
        db_p = Path(self.path)
        if db_p.is_absolute():
            return db_p
        return (base_dir / db_p).resolve()


class OllamaConfig(BaseModel):
    base_url: str = "http://127.0.0.1:11434"
    model: str = "gemma2:9b"
    timeout_seconds: float = 120.0


class ImapConfig(BaseModel):
    host: str = "imap.gmail.com"
    port: int = 993
    use_ssl: bool = True
    username: str = ""
    password: str = ""
    mailbox: str = "INBOX"
    poll_interval_seconds: int = 900


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EMAIL_AGENT_",
        env_nested_delimiter="__",
        extra="ignore"
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    imap: ImapConfig = Field(default_factory=ImapConfig)

    @classmethod
    def load_from_yaml(cls, yaml_path: Optional[Path] = None) -> "AppSettings":
        """
        Loads configuration from a YAML file if present,
        allowing environment variables to override.
        """
        data = {}
        if yaml_path and yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    data = loaded

        return cls(**data)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """
    Returns the cached application settings.
    Discovers config.yaml by searching the current directory and parents.
    """
    current = Path(__file__).resolve().parent
    # Check parent directories for config.yaml (e.g. backend/ or workspace root)
    candidates = [
        current.parent.parent / "config.yaml",  # root/config.yaml
        current.parent / "config.yaml",         # backend/config.yaml
        Path.cwd() / "config.yaml",
    ]

    config_file: Optional[Path] = None
    for candidate in candidates:
        if candidate.exists():
            config_file = candidate
            break

    return AppSettings.load_from_yaml(config_file)
