"""猫猫小助手四类一级咨询入口与确定性下单指引。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ConsultationRoute:
    key: str
    intent: str
    label: str
    intro: str
    questions: tuple[str, ...]


ROUTES: tuple[ConsultationRoute, ...] = (
    ConsultationRoute(
        key="order",
        intent="consult_order",
        label="下单问题咨询",
        intro=(
            "已进入下单问题咨询。下单流程是：登录账号 → 选择设备和配置 → "
            "填写租期与数量 → 查库存并核对价格 → 填写收货信息 → 确认下单 → 等待商家审核。请选择你想了解的问题："
        ),
        questions=(
            "下单流程是什么？",
            "我后天要用，什么时候下单合适？",
            "如何查询库存和价格？",
            "可以修改或取消订单吗？",
        ),
    ),
    ConsultationRoute(
        key="deposit",
        intent="consult_deposit",
        label="免押问题咨询",
        intro="已进入免押问题咨询。你可以了解免押条件、信用要求、额度冻结和押金退还规则：",
        questions=(
            "免押需要什么条件？",
            "我没有芝麻信用，可以免押金吗？",
            "押金多久退？",
            "免押会冻结额度吗？",
        ),
    ),
    ConsultationRoute(
        key="claim",
        intent="consult_claim",
        label="理赔问题咨询",
        intro="已进入理赔问题咨询。这里可以查看申请流程、扣费标准、争议处理和维修期间计费：",
        questions=(
            "发现损坏后，怎么申请理赔？",
            "相机磕碰如何扣费？",
            "对理赔结果有异议怎么办？",
            "维修期间，租金怎么算？",
        ),
    ),
    ConsultationRoute(
        key="device",
        intent="consult_device",
        label="设备选择咨询",
        intro="已进入设备选择咨询。可以直接选一个场景，也可以告诉我用途；我会逐步反问并帮你选设备、问免押、带入下单：",
        questions=(
            "开始帮我选设备",
            "镜头怎么选？我不懂参数。",
            "我是新手，去川西旅游，推荐哪款相机？",
            "我要去看演唱会，坐内场前几排，租什么合适？",
        ),
    ),
)

_ROUTE_BY_KEY = {route.key: route for route in ROUTES}


def _normalize(message: str) -> str:
    return re.sub(r"[\s，。！？、:：.．\-]+", "", message.strip()).lower()


def _route_aliases(route: ConsultationRoute, index: int) -> set[str]:
    return {
        _normalize(route.label),
        _normalize(f"进入{route.label}"),
        _normalize(f"{index}.{route.label}"),
        _normalize(f"{index}、{route.label}"),
    }


def enter(message: str) -> Optional[dict]:
    """只匹配受控一级入口，避免宽泛词抢占正常业务意图。"""
    normalized = _normalize(message)
    for index, route in enumerate(ROUTES, start=1):
        if normalized not in _route_aliases(route, index):
            continue
        return {
            "route": route.key,
            "intent": route.intent,
            "text": route.intro,
            "actions": [
                {
                    "type": "button",
                    "label": question,
                    "action": "consult_question",
                    "payload": {"route": route.key, "question": question},
                }
                for question in route.questions
            ],
        }
    return None


_COMMON_ORDER_ANSWERS = {
    _normalize("下单流程是什么？"): {
        "intent": "order_guide",
        "text": (
            "请先登录账号，在左侧选择设备和配置，填写起租日、归还日及数量；点击“查库存 & 算价格”，"
            "确认租金和押金展示，填写收货人、手机号、省市区和详细地址后点击“确认地址并立即下单”。"
            "订单创建后由商家审核，审核通过后进入待发货。"
        ),
        "actions": [{"type": "button", "label": "去选择设备", "action": "scroll_order"}],
    },
    _normalize("如何查询库存和价格？"): {
        "intent": "order_guide",
        "text": (
            "在左侧选中相机和具体配置，填写起租日、归还日与数量，再点击“查库存 & 算价格”。"
            "页面会按真实档期显示可租数量、租金、押金展示和应付租金；库存不足时不能提交订单。"
        ),
        "actions": [{"type": "button", "label": "去查库存和价格", "action": "scroll_order"}],
    },
    _normalize("可以修改或取消订单吗？"): {
        "intent": "order_guide",
        "text": (
            "待支付订单可在“我的订单”中取消。若要修改设备、数量或租期，请咨询客服确认库存和差价；"
            "商家审核通过或已经发货后，取消与变更也需咨询客服按当前订单状态处理。"
        ),
        "actions": [],
    },
}


def answer_common(message: str) -> Optional[dict]:
    """补齐知识库未覆盖、但由当前页面能力可以确定回答的下单问题。"""
    result = _COMMON_ORDER_ANSWERS.get(_normalize(message))
    return dict(result) if result else None


def get_route(key: str) -> Optional[ConsultationRoute]:
    return _ROUTE_BY_KEY.get(key)
