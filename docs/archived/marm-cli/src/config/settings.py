"""Configuration management using Pydantic"""
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import List, Optional
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


class OllamaConfig(BaseModel):
    """Ollama server configuration"""
    base_url: str = "http://localhost:11434"
    model: str = "codellama:13b"
    timeout: int = 120
    keep_alive: str = "5m"


class MARMConfig(BaseModel):
    """MARM memory layer configuration"""
    database_path: str = ".marm-cli/conversations.db"
    embeddings_cache: str = ".marm-cli/embeddings"
    auto_log_enabled: bool = True
    auto_refresh_enabled: bool = True
    context_bridge_enabled: bool = True
    refresh_interval_minutes: int = 30
    refresh_message_threshold: int = 50
    refresh_idle_minutes: int = 10


class UIConfig(BaseModel):
    """UI configuration"""
    theme: str = "dark"
    show_timestamps: bool = True
    markdown_enabled: bool = True
    syntax_highlighting: bool = True

    # Keyboard shortcut warnings
    skip_clear_warning: bool = False
    skip_exit_warning: bool = False


class ModelsConfig(BaseModel):
    """Available models configuration"""
    available: List[str] = ["codellama:7b", "codellama:13b", "codellama:34b"]


class Settings(BaseSettings):
    """Main application settings"""
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    marm: MARMConfig = Field(default_factory=MARMConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @classmethod
    def load_from_file(cls, config_path: str = "config/settings.json") -> "Settings":
        """Load settings from JSON file"""
        path = Path(config_path)

        if not path.exists():
            logger.warning(f"Config file not found: {config_path}, using defaults")
            return cls()

        try:
            with open(path, "r") as f:
                config_data = json.load(f)

            logger.info(f"Loaded configuration from {config_path}")
            return cls(**config_data)

        except Exception as e:
            logger.error(f"Error loading config: {e}, using defaults")
            return cls()

    def save_to_file(self, config_path: str = "config/settings.json"):
        """Save settings to JSON file"""
        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w") as f:
                json.dump(self.model_dump(), f, indent=2)

            logger.info(f"Settings saved to {config_path}")

        except Exception as e:
            logger.error(f"Error saving config: {e}")


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get global settings instance (singleton)"""
    global _settings

    if _settings is None:
        _settings = Settings.load_from_file()

    return _settings


def reload_settings():
    """Reload settings from file"""
    global _settings
    _settings = Settings.load_from_file()
    return _settings
