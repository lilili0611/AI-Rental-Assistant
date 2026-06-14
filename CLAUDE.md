# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

相机租赁 AI 助手 (Camera Rental AI Assistant) — FastAPI backend + 单页静态前端，对接飞书数据，面向客户与内部员工。已实现 Phase 1（自助查询）+ Phase 2（订单与飞书同步）。

## Commands

```bash
# 环境
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 初始化/重置数据库（删 rental.db 后重跑即可重置）；会打印演示 user_id 与配置 ID
python -m scripts.seed_data

# 启动服务（API 文档 http://127.0.0.1:8000/docs，前端 http://127.0.0.1:8000/）
uvicorn app.main:app --reload

# 单元测试
pytest -q
pytest tests/test_pricing.py -q                    # 单文件
pytest tests/test_orders.py::test_xxx -q           # 单用例

# 端到端测试（Playwright）—— 需先启动 uvicorn，再另开终端运行
cd tests-e2e && npm install && node test.js
```

工作流铁律：每次迭代**先更新** `files/PRD_相机租赁AI助手.md` 和 `files/Spec_相机租赁AI助手.md`，再写代码。

## Architecture

分层：`api/`（路由）→ `services/`（业务逻辑）→ `models/`（SQLAlchemy ORM）。`schemas/` 是 Pydantic 请求/响应。所有 ORM 模型必须在 `app/models/__init__.py` 导出，`main.py` 靠导入它来注册到 metadata 并 `create_all`。

`app/main.py` 的 lifespan 在启动时建表并启动 `scheduler.py` 的 APScheduler——每分钟扫描并释放过期预留（替代 Celery）；`feishu_enabled=true` 时额外加飞书轮询任务。

### 三个核心约定（改动前必读，对照 Spec §10）

1. **按日期库存** (`services/inventory_service.py`) — 库存不是全局计数。每条 `Occupancy` 记录占 1 台并带 `[start_date, end_date]` 区间；某配置在租期能租几台 = 区间内**逐日**可用量的**最小值**。改单时用 `exclude_ref_id` 排除自身占用。设备/配置表上**没有**库存字段，配置只有 `total_units`；库存只能通过 `/api/inventory/available` 按日期查询。

2. **档位计价** (`services/pricing_service.py`) — 不是日租×折扣。1–2 天用 `two_day_price`，3 天用 `three_day_price`，>3 天 = `three_day_price + (天数-3) × extra_day_price`。天数含起含止（9/1–9/3 = 3 天）。原 PRD 的天数阶梯/季节折扣已废弃。

3. **无支付通道** — 没有任何在线支付/二维码。收款由 staff 人工确认（`POST /api/orders/{id}/confirm-payment` 写入 `paid_amount` + `payment_note`）。

### 订单状态机与并发 (`services/order_service.py`)

`ALLOWED_TRANSITIONS` 定义合法流转：`draft → pending_payment → paid → confirmed → shipped → active → returned → completed`，多数状态可 `→ cancelled`（已发货后不可直接取消）。所有变更走乐观锁：调用方传 `version`，不匹配抛 `version_conflict`，成功后 `version += 1`。取消时按 `business_rules` 算手续费并释放占用（把对应 `Occupancy.status` 置 `released`）。预留转单不重复占用——下单时复用预留的占用记录而非新建。

### 意图识别 (`app/intent/recognizer.py`)

`recognize()` 优先调 DeepSeek LLM（`integrations/llm.py`，OpenAI 兼容）；未配置 `DEEPSEEK_API_KEY` 或失败时自动降级到关键词规则 `_rule_intent`。`config.settings.llm_enabled` 反映是否启用。

### 其它

- `core/business_rules.py` — 损坏赔偿查表（左开右闭区间，按尺寸 mm 返回押金扣除比例）。定价常量已迁出到 pricing_service。
- `core/security.py` — 敏感字段加密**占位实现**，生产需替换为真实 AES-256-GCM。
- 认证（MVP）：请求头 `X-User-Id: <用户ID>`（见 `api/deps.py`）。staff-only 接口校验 role。
- `services/session_store.py` — 会话存储，预留可换 Redis 的接口。
- 数据库默认 SQLite（`rental.db`），架构按可迁移 PostgreSQL 设计。

## 待外部输入的占位项

- `DEEPSEEK_API_KEY`（启用真实意图识别）
- 飞书：`FEISHU_ENABLED=true` + App ID/Secret/Bitable token；`integrations/feishu.py` 轮询回流逻辑待凭证就绪后补完
- `core/business_rules.py` 赔偿区间待业务方最终确认
- `core/security.py` 生产级加密
