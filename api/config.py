from pydantic_settings import BaseSettings
from enum import Enum
from pydantic import Field
import json
import os

DATA_DIR = "data"
ORIGINAL_CONFIG_FILE = "renamer_config.json"
NEW_CONFIG_FILE = os.path.join(DATA_DIR, "metadata_api_config.json")


class DeploymentMode(str, Enum):
    LOCAL = "local"
    REMOTE = "remote"


class Settings(BaseSettings):
    mode: DeploymentMode = DeploymentMode.LOCAL
    host: str = "0.0.0.0"
    port: int = 8000

    # Header 认证密钥（所有 API 请求需在 Authorization 或 Authentication 头携带此密钥，留空则不启用）
    auth_key: str = ""

    # TMDb/BGM 配置
    tmdb_api_key: str = ""
    bgm_api_key: str = ""

    # AI 配置（OpenAI 兼容 API，用于从目录路径推断剧名/电影名）
    ai_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com"
    ai_model: str = "deepseek-v4-flash"
    ai_max_tokens: int = 10000

    # Web UI 登录凭证（留空则不需要登录）
    web_username: str = Field("", validation_alias="METADATA_WEB_USERNAME")
    web_password: str = Field("", validation_alias="METADATA_WEB_PASSWORD")

    # 媒体库目录路径（整理/刮削的默认目标目录）
    media_library: str = Field("/media/library", validation_alias="MEDIA_LIBRARY")

    class Config:
        env_prefix = "METADATA_"

    def save_to_file(self):
        config_dict = {
            "tmdb_api_key": self.tmdb_api_key,
            "bgm_api_key": self.bgm_api_key,
            "ai_base_url": self.ai_base_url,
            "ai_model": self.ai_model,
            "ai_max_tokens": self.ai_max_tokens,
            "media_library": self.media_library,
        }
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
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
        if "auth_key" in config_dict and not os.environ.get("METADATA_AUTH_KEY"):
            self.auth_key = config_dict.get("auth_key", "")
        if "tmdb_api_key" in config_dict and not os.environ.get("METADATA_TMDB_API_KEY"):
            self.tmdb_api_key = config_dict.get("tmdb_api_key", "")
        if "bgm_api_key" in config_dict and not os.environ.get("METADATA_BGM_API_KEY"):
            self.bgm_api_key = config_dict.get("bgm_api_key", "")
        if "ai_api_key" in config_dict and not os.environ.get("METADATA_AI_API_KEY"):
            self.ai_api_key = config_dict.get("ai_api_key", "")
        if "ai_base_url" in config_dict:
            self.ai_base_url = config_dict.get("ai_base_url", "https://api.deepseek.com")
        if "ai_model" in config_dict:
            self.ai_model = config_dict.get("ai_model", "deepseek-v4-flash")
        if "ai_max_tokens" in config_dict:
            self.ai_max_tokens = int(config_dict.get("ai_max_tokens", 10000))
        if "media_library" in config_dict and not os.environ.get("MEDIA_LIBRARY"):
            self.media_library = config_dict.get("media_library", "/media/library")


settings = Settings()
settings.load_from_file()