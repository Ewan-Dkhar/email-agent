"""
Configuration Management Module.
Implements hierarchical configuration loading:
Default Values -> config.yaml -> Environment Variable Overrides.
"""

from pathlib import Path
from typing import Optional, Tuple, Type
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)
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


class SmtpConfig(BaseModel):
    host: str = "smtp.gmail.com"
    port: int = 587
    use_tls: bool = True
    use_ssl: bool = False
    username: str = ""
    password: str = ""
    from_address: str = ""

    def get_username(self, fallback_imap: str = "") -> str:
        return self.username or fallback_imap

    def get_password(self, fallback_imap: str = "") -> str:
        return self.password or fallback_imap

    def get_from_address(self, fallback: str = "") -> str:
        return self.from_address or self.username or fallback


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
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> Tuple[PydanticBaseSettingsSource, ...]:
        # Priority order: Environment Variables -> YAML (via init) -> Defaults
        return (
            env_settings,
            init_settings,
            dotenv_settings,
            file_secret_settings,
        )

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
