from pydantic_settings import BaseSettings
from enum import Enum
import json
import os
from dotenv import load_dotenv

load_dotenv()

ORIGINAL_CONFIG_FILE = "renamer_config.json"
NEW_CONFIG_FILE = "media_renamer_config.json"


class DeploymentMode(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class Settings(BaseSettings):
    mode: DeploymentMode = DeploymentMode.LOCAL
    host: str = "0.0.0.0"
    port: int = 8000

    # TMDb/BGM 配置
    tmdb_api_key: str = ""
    bgm_api_key: str = ""

    # AI 配置（OpenAI 兼容 API，用于从目录路径推断剧名/电影名）
    ai_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com"
    ai_model: str = "deepseek-v4-pro"
    ai_max_tokens: int = 10000

    class Config:
        env_prefix = "MEDIA_RENAMER_"

    def save_to_file(self):
        config_dict = {
            "tmdb_api_key": self.tmdb_api_key,
            "bgm_api_key": self.bgm_api_key,
            "ai_api_key": self.ai_api_key,
            "ai_base_url": self.ai_base_url,
            "ai_model": self.ai_model,
            "ai_max_tokens": self.ai_max_tokens,
        }
        try:
            with open(NEW_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config_dict, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load_from_file(self):
        if os.path.exists(NEW_CONFIG_FILE):
            try:
                with open(NEW_CONFIG_FILE, "r", encoding="utf-8") as f:
                    config_dict = json.load(f)
                    self._apply_config_dict(config_dict)
                return True
            except Exception:
                pass

        if os.path.exists(ORIGINAL_CONFIG_FILE):
            try:
                with open(ORIGINAL_CONFIG_FILE, "r", encoding="utf-8") as f:
                    config_dict = json.load(f)
                    self._apply_config_dict(config_dict)
                return True
            except Exception:
                pass

        return False

    def _apply_config_dict(self, config_dict: dict):
        if "tmdb_api_key" in config_dict and not os.environ.get("MEDIA_RENAMER_TMDB_API_KEY"):
            self.tmdb_api_key = config_dict.get("tmdb_api_key", "")
        if "bgm_api_key" in config_dict and not os.environ.get("MEDIA_RENAMER_BGM_API_KEY"):
            self.bgm_api_key = config_dict.get("bgm_api_key", "")
        if "ai_api_key" in config_dict and not os.environ.get("MEDIA_RENAMER_AI_API_KEY"):
            self.ai_api_key = config_dict.get("ai_api_key", "")
        if "ai_base_url" in config_dict:
            self.ai_base_url = config_dict.get("ai_base_url", "https://api.deepseek.com")
        if "ai_model" in config_dict:
            self.ai_model = config_dict.get("ai_model", "deepseek-v4-pro")
        if "ai_max_tokens" in config_dict:
            self.ai_max_tokens = int(config_dict.get("ai_max_tokens", 10000))


settings = Settings()
settings.load_from_file()