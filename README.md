# 相机租赁 AI 助手系统

对接飞书数据、面向客户与内部员工的 AI 租赁管理助手。本仓库实现 **Phase 1（自助查询）+ Phase 2（订单与同步）**。

> 配套文档：[PRD](files/PRD_相机租赁AI助手.md) · [Spec](files/Spec_相机租赁AI助手.md)

正式域名规划：
- 客户前端：`https://bozipaopao.cn/`
- 商家后台：`https://admin.bozipaopao.cn/`

## 技术栈

| 层 | 选型 |
|----|------|
| Web 框架 | FastAPI |
| ORM | SQLAlchemy 2.0 |
| 数据库 | SQLite（起步，架构可平滑迁移 PostgreSQL）|
| 数据验证 | Pydantic 2 |
| 定时任务 | APScheduler（替代 Celery，扫描预留过期与订单超时）|
| LLM | DeepSeek（OpenAI 兼容；未配置 Key 时自动降级到关键词规则）|
| 飞书 | httpx 直连（Phase 2，默认关闭）|

## 已落实的 6 项关键修正（对照 Spec §10）

1. **按日期库存**：占用记录挂在 `occupancy` 表，按 `[start, end]` 区间逐日计算可用量，取区间最小值；不再用全局计数。
2. 设备/配置表移除库存计数字段，配置只保留 `total_units`。
3. 移除任何支付通道/二维码；支付由**人工确认**（`paid_amount` + `payment_note`）。
4. 预留带 `rental_start/rental_end` 日期区间。
5. 库存查询返回 `min_available_in_range` + 每日明细。
6. 设备列表不挂库存，库存只在库存 API 按日期返回。

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置环境变量（可选，不配也能跑）
cp .env.example .env
#   填入 DEEPSEEK_API_KEY 即启用真实大模型意图识别；留空则用关键词规则

# 3. 初始化演示数据（建表 + 真实设备目录 + 演示账号）
python -m scripts.seed_data
#   会打印租客邮箱账号和商家后台账号

# 4. 启动服务
uvicorn app.main:app --reload
#   API 文档: http://127.0.0.1:8000/docs
```

> 想重置数据：删除 `rental.db` 后重新执行 `python -m scripts.seed_data`。

## 测试

```bash
source .venv/bin/activate
pytest -q
```

覆盖 Spec §9 关键路径：按日期库存、折扣叠加与边界、预留过期释放、订单状态机、乐观锁冲突、人工收款、预留转单不重复占用、取消释放库存、超时订单自动取消。

## 主要 API

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/cameras` | 设备列表 | 否 |
| GET | `/api/cameras/{id}` | 设备详情含配置 | 否 |
| GET | `/api/inventory/available` | **按日期查可用库存** | 否 |
| GET | `/api/pricing/calculate` | 价格计算 | 否 |
| POST | `/api/chat` | AI 对话（意图识别）| 可选 |
| POST | `/api/reservations` | 创建预留（锁定30分钟）| 可选 |
| POST | `/api/orders` | 创建订单 | 是 |
| GET | `/api/orders` / `/api/orders/{id}` | 查询订单 | 是 |
| PATCH | `/api/orders/{id}` | 改期（乐观锁）| 是 |
| DELETE | `/api/orders/{id}` | 取消（按规则算手续费）| 是 |
| POST | `/api/orders/{id}/confirm-payment` | **人工确认收款** | staff |
| POST | `/api/orders/{id}/advance` | 推进状态（审核/发货/签收/归还/完成）| staff |

认证：租客使用邮箱 + 密码注册/登录，服务端写入 HttpOnly 登录 Cookie；后续浏览器请求会自动携带登录态。商家后台仍使用员工手机号 + 密码登录。

## 目录结构

```
app/
  config.py            # 配置（环境变量）
  database.py          # 数据库引擎/会话
  main.py              # FastAPI 入口
  scheduler.py         # 定时任务（预留过期 / 订单超时扫描）
  models/              # ORM 模型
  schemas/             # Pydantic 请求/响应
  services/            # 业务逻辑
    inventory_service.py   # 🔴 按日期库存算法（核心）
    pricing_service.py     # 价格计算
    reservation_service.py # 预留与释放
    order_service.py       # 订单状态机/乐观锁/取消/收款
    chat_service.py        # 对话编排
    session_store.py       # 会话存储（可换 Redis）
  intent/              # 意图识别（LLM + 规则降级）
  integrations/        # llm.py(DeepSeek) / feishu.py(飞书同步)
  core/                # business_rules.py（折扣/赔偿表）/ security.py（加密）
scripts/seed_data.py   # 演示数据
tests/                 # pytest
```

## 待办与依赖外部输入

- **DeepSeek Key**：填入 `.env` 的 `DEEPSEEK_API_KEY` 即启用真实意图识别。
- **飞书同步**：将 `.env` 中 `FEISHU_ENABLED=true` 并填入 App ID/Secret/多维表格 token 后启用；`app/integrations/feishu.py` 的轮询回流逻辑待凭证就绪后补完。
- **季节折扣日历**：`app/core/business_rules.py` 的 `SEASONAL_DISCOUNT` 目前仅 9 月示例，待业务方提供完整年度日历。
- **赔偿区间**：`business_rules.py` 已按左开右闭整理，待业务方对照实物习惯最终确认。
- **生产加密**：`core/security.py` 为占位实现，生产应替换为 `cryptography` 的 AES-256-GCM。
