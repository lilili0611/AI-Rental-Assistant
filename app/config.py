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
    # 旧版手机号直登兼容入口；生产默认关闭，避免公网制造垃圾用户
    enable_phone_login: bool = False
    # 生产 HTTPS 环境应设为 true；本地 http 开发保持 false
    session_cookie_secure: bool = False

    # 业务参数
    reservation_ttl_minutes: int = 30  # 库存预留时长
    unpaid_order_ttl_hours: int = 1  # 客户未付款自动取消窗口
    merchant_review_ttl_hours: int = 12  # 已收款但商家未确认档期的自动取消窗口
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
