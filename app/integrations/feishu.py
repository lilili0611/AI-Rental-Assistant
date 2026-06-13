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
FIELD_MAPPING = {
    "id": "订单号",
    "status": "订单状态",
    "rental_start": "租期开始",
    "rental_end": "租期结束",
    "total_price": "应付金额",
    "paid_amount": "已收金额",
    "payment_note": "收款备注",
}

# 飞书 -> AI 回流: 订单状态文本归一(接受中英文)
_VALID_STATUS = {
    "draft", "pending_payment", "paid", "confirmed", "shipped",
    "active", "returned", "completed", "cancelled",
}
_STATUS_ALIASES = {
    "草稿": "draft", "待支付": "pending_payment", "待付款": "pending_payment",
    "已支付": "paid", "已付款": "paid", "已收款": "paid",
    "已确认": "confirmed", "已审核": "confirmed", "已发货": "shipped",
    "使用中": "active", "已签收": "active", "已归还": "returned",
    "已完成": "completed", "已取消": "cancelled",
}


def _text(v) -> Optional[str]:
    """飞书文本字段可能是字符串或富文本段数组, 统一取纯文本。"""
    if v is None:
        return None
    if isinstance(v, list):
        return "".join(seg.get("text", "") for seg in v if isinstance(seg, dict)) or None
    return str(v)


def _norm_status(v) -> Optional[str]:
    s = _text(v)
    if not s:
        return None
    s = s.strip()
    if s in _VALID_STATUS:
        return s
    return _STATUS_ALIASES.get(s)

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


def _list_all_records(client: httpx.Client, token: str) -> list:
    """分页拉取订单表全部记录。"""
    items, page_token = [], None
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(50):  # 安全上限
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        data = client.get(_records_url(), headers=headers, params=params).json()
        d = data.get("data", {}) or {}
        items.extend(d.get("items", []) or [])
        if d.get("has_more") and d.get("page_token"):
            page_token = d["page_token"]
        else:
            break
    return items


def poll_changes_job():
    """飞书 -> AI: 轮询飞书表, 把人工在飞书的改动回流到本地 (Spec 7)。

    冲突策略(无飞书时间戳时的务实做法):
      - 本地有未推送改动(sync_status=='sync_pending') -> 本地优先, 重推飞书, 跳过回流;
      - 否则飞书值与本地不同 -> 视为人工在飞书修改 -> 回流更新本地(状态/已收/备注)。
    同步后两边一致, 天然防回环。变更写 order_changes 审计, source 置 feishu。
    """
    if not _enabled():
        return
    from decimal import Decimal

    from app.database import SessionLocal
    from app.models.order import Order, OrderChange

    db = SessionLocal()
    try:
        token = get_tenant_token()
        with httpx.Client(timeout=20) as client:
            records = _list_all_records(client, token)
        changed = 0
        for it in records:
            f = it.get("fields", {}) or {}
            oid = _text(f.get(FIELD_MAPPING["id"]))
            if not oid:
                continue
            order = db.get(Order, oid)
            if not order:  # 飞书里的设备行等非本系统订单, 跳过
                continue

            # 本地有未推送改动 -> 本地优先, 重推飞书
            if order.sync_status == "sync_pending":
                if push_order(order):
                    order.sync_status = "synced"
                    db.commit()
                continue

            updates = {}
            fstatus = _norm_status(f.get(FIELD_MAPPING["status"]))
            if fstatus and fstatus != order.status:
                updates["status"] = (order.status, fstatus)

            fpaid_raw = f.get(FIELD_MAPPING["paid_amount"])
            if fpaid_raw is not None and fpaid_raw != "":
                try:
                    fpaid = Decimal(str(fpaid_raw))
                    if fpaid != order.paid_amount:
                        updates["paid_amount"] = (order.paid_amount, fpaid)
                except (ValueError, ArithmeticError):
                    pass

            fnote = _text(f.get(FIELD_MAPPING["payment_note"]))
            if (fnote or None) != (order.payment_note or None):
                updates["payment_note"] = (order.payment_note, fnote)

            if not updates:
                continue

            # 回流: 飞书 -> 本地
            if "status" in updates:
                order.status = updates["status"][1]
            if "paid_amount" in updates:
                order.paid_amount = updates["paid_amount"][1]
            if "payment_note" in updates:
                order.payment_note = updates["payment_note"][1]
            order.version += 1
            order.source = "feishu"
            order.sync_status = "synced"
            db.add(OrderChange(
                order_id=order.id, change_type="feishu_sync", changed_by=None,
                old_value={k: str(v[0]) for k, v in updates.items()},
                new_value={k: str(v[1]) for k, v in updates.items()},
                reason="飞书回流",
            ))
            changed += 1
        if changed:
            db.commit()
            logger.info("飞书回流: 更新 %d 单", changed)
    except Exception:  # noqa: BLE001
        logger.exception("飞书回流失败")
    finally:
        db.close()
