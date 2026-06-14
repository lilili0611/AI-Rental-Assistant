"""全局配置：从环境变量 / .env 读取。"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # 数据库
    database_url: str = "sqlite:///./rental.db"

    # DeepSeek LLM
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 加密
    encryption_key: str = "change-me-in-production-please-32b"

    # 部署: 启动时若数据库为空则自动灌入演示目录(云端首次部署用; 数据库非空则不动)
    auto_seed: bool = False

    # 业务参数
    reservation_ttl_minutes: int = 30  # 库存预留时长
    free_cancel_hours: int = 48  # 未支付免费取消窗口
    cancellation_fee_rate: float = 0.10  # 已支付取消手续费率
    late_fee_rate: float = 0.10  # 滞纳金费率(日租金的百分比)

    # 飞书 (Phase 2)
    feishu_enabled: bool = False
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_bitable_app_token: str = ""
    feishu_order_table_id: str = ""

    @property
    def llm_enabled(self) -> bool:
        return bool(self.deepseek_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
