"""飞书双向同步 (Spec 7) —— Phase 2。

⚠️ 默认关闭 (FEISHU_ENABLED=false)。启用需提供:
  FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_BITABLE_APP_TOKEN / FEISHU_ORDER_TABLE_ID

同步方向:
  AI -> 飞书: 订单创建/状态变更时写入飞书多维表格(失败重试3次, 仍失败标 sync_pending)。
  飞书 -> AI: 每30秒轮询最近变更 + Webhook 推送。
冲突解决: 比较 last_modified_at 时间戳, 后改胜出; 乐观锁 version 防并发覆盖。

本文件目前提供接口骨架与字段映射, 具体 API 调用待飞书凭证就绪后实现。
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger("feishu")

# 字段映射 (Spec 7.2)。value 为飞书表中的实际列名(对齐用户最新表结构)。
# 注: 主列名为「设备编号」, 订单号写入该列。
FIELD_MAPPING = {
    "id": "设备编号",
    "status": "订单状态",
    "rental_start": "租期开始",
    "rental_end": "租期结束",
    "total_price": "应付金额",
    "paid_amount": "已收金额",
    "payment_note": "收款备注",
}

_token_cache = {"token": None, "expire_at": 0.0}


def _enabled() -> bool:
    return settings.feishu_enabled and bool(settings.feishu_app_id)


def get_tenant_token() -> Optional[str]:
    """获取 tenant_access_token (带缓存)。"""
    if not _enabled():
        return None
    if _token_cache["token"] and _token_cache["expire_at"] > time.time():
        return _token_cache["token"]
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    with httpx.Client(timeout=10) as client:
        resp = client.post(url, json={
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret,
        })
        resp.raise_for_status()
        data = resp.json()
    token = data.get("tenant_access_token")
    _token_cache["token"] = token
    _token_cache["expire_at"] = time.time() + data.get("expire", 7200) - 300
    return token


def _records_url() -> str:
    return (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/"
        f"{settings.feishu_bitable_app_token}/tables/"
        f"{settings.feishu_order_table_id}/records"
    )


def _build_fields(order) -> dict:
    """把订单对象转成飞书表字段。数字列传 number, 其余传文本字符串。"""
    return {
        FIELD_MAPPING["id"]: order.id,
        FIELD_MAPPING["status"]: order.status,
        FIELD_MAPPING["total_price"]: float(order.total_price),
        FIELD_MAPPING["paid_amount"]: float(order.paid_amount),
        FIELD_MAPPING["rental_start"]: order.rental_start.isoformat(),
        FIELD_MAPPING["rental_end"]: order.rental_end.isoformat(),
        FIELD_MAPPING["payment_note"]: order.payment_note or "",
    }


def _find_record_id(client: httpx.Client, token: str, order_id: str) -> Optional[str]:
    """按主列(订单号)查已存在记录的 record_id; 没有返回 None。"""
    resp = client.post(
        f"{_records_url()}/search",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "filter": {
                "conjunction": "and",
                "conditions": [
                    {
                        "field_name": FIELD_MAPPING["id"],
                        "operator": "is",
                        "value": [order_id],
                    }
                ],
            }
        },
    )
    items = (resp.json().get("data", {}) or {}).get("items", []) or []
    return items[0]["record_id"] if items else None


def push_order(order) -> bool:
    """AI -> 飞书: upsert 订单行(存在则更新, 否则新建)。失败重试 3 次。

    返回是否成功; 调用方据此设置 order.sync_status。
    """
    if not _enabled():
        return False
    fields = _build_fields(order)
    for attempt in range(3):
        try:
            token = get_tenant_token()
            with httpx.Client(timeout=15) as client:
                headers = {"Authorization": f"Bearer {token}"}
                record_id = _find_record_id(client, token, order.id)
                if record_id:
                    resp = client.put(
                        f"{_records_url()}/{record_id}",
                        headers=headers,
                        json={"fields": fields},
                    )
                else:
                    resp = client.post(
                        _records_url(), headers=headers, json={"fields": fields}
                    )
                resp.raise_for_status()
                body = resp.json()
                if body.get("code") not in (0, None):
                    raise RuntimeError(f"feishu code={body.get('code')} msg={body.get('msg')}")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("飞书写入失败(%s), 重试 %d/3", e, attempt + 1)
            time.sleep(2 ** attempt)  # 指数退避
    logger.error("飞书写入最终失败: order=%s", order.id)
    return False


def poll_changes_job():
    """飞书 -> AI: 轮询最近变更 (由定时任务每 30 秒调用)。

    待实现: 拉取飞书表近期变更行, 按 last_modified_at 做冲突裁决后回写本地。
    """
    if not _enabled():
        return
    logger.debug("飞书轮询占位: 待凭证就绪后实现")
