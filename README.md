# 相机租赁 AI 助手系统

对接飞书数据、面向客户与内部员工的 AI 租赁管理助手。当前 **v2.10.6** 已把手机端语音入口整合到 AI 文字输入框右侧：按住麦克风识别、松开发送，键盘输入与独立发送按钮继续保留。

线上地址：[https://bozipaopao.cn/](https://bozipaopao.cn/)（Vercel 托管，当前版本 v2.10.6）。

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
| 知识问答 | 52 条真实客服 FAQ 本地检索，知识库优先 |
| LLM | DeepSeek（OpenAI 兼容；仅兜底合理的未知导购问题）|
| 全流程陪伴 | 多轮反问导购、移动端文字/语音入口、免押说明、下单带入、设备指南、站内提醒与租后反馈 |
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
#   填入 DEEPSEEK_API_KEY 即启用意图识别和未知导购问题兜底
#   留空时 FAQ/业务查询仍可用，无法回答的问题会提示咨询客服

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

覆盖 Spec §9/§13–§16/§20–§28 关键路径：按日期库存、价格边界、预留释放、订单状态机、人工收款、终态订单删除与审计保留、收货地址校验与权限、个人信息脱敏、知识库优先、四类咨询路由、LLM 180 字硬上限、多轮导购、全阶段发散问答、确认关系与跨实例恢复、输入框内麦克风与移动端语音降级、用户资料与密码安全、设备/租期/收货信息下单带入、陪伴提醒和安全排障。

## 主要 API

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| GET | `/api/cameras` | 设备列表 | 否 |
| GET | `/api/cameras/{id}` | 设备详情含配置 | 否 |
| GET | `/api/inventory/available` | **按日期查可用库存** | 否 |
| GET | `/api/pricing/calculate` | 价格计算 | 否 |
| POST | `/api/chat` | AI 对话（安全拦截 → 使用支持/主动导购 → FAQ → 业务数据 → LLM 兜底）| 可选 |
| GET/PATCH | `/api/auth/me` | 查看或修改本人昵称、邮箱和头像 | 是 |
| POST | `/api/auth/change-password` | 校验当前密码后修改登录密码 | 是 |
| POST | `/api/reservations` | 创建预留（锁定30分钟）| 可选 |
| POST | `/api/orders` | 创建订单 | 是 |
| GET | `/api/orders` / `/api/orders/{id}` | 查询订单 | 是 |
| PATCH | `/api/orders/{id}` | 改期（乐观锁）| 是 |
| DELETE | `/api/orders/{id}` | 取消（按规则算手续费）| 是 |
| DELETE | `/api/orders/{id}/record` | 从本人列表删除已取消/已完结订单（保留后台审计）| 订单本人 |
| POST | `/api/orders/{id}/confirm-payment` | **人工确认收款** | staff |
| POST | `/api/orders/{id}/advance` | 推进状态（审核/发货/签收/归还/完成）| staff |
| GET | `/api/orders/{id}/companion` | 订单阶段、人工运单、设备指南、归还提醒 | 订单本人 |
| POST | `/api/orders/{id}/feedback` | 完结订单评价与自愿作品分享 | 订单本人 |
| GET | `/api/community/showcase` | 已获授权的匿名作品链接 | 否 |

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
    order_service.py       # 订单状态机/乐观锁/取消/租客侧删除/收款
    chat_service.py        # 对话编排
    sales_guide.py         # 主动反问、推荐、免押与下单带入
    companion_service.py   # 租中/租后阶段与幂等提醒
    usage_support.py       # 快速上手和安全故障排查
    session_store.py       # 会话存储（可换 Redis）
  knowledge_base/      # 52条真实客服FAQ + 本地检索 + 短回复导购兜底
  intent/              # 意图识别（LLM + 规则降级）
  integrations/        # llm.py(DeepSeek) / feishu.py(飞书同步)
  core/                # business_rules.py（折扣/赔偿表）/ security.py（加密）
scripts/seed_data.py   # 演示数据
tests/                 # pytest
```

## 待办与依赖外部输入

- **DeepSeek Key**：填入 `.env` 的 `DEEPSEEK_API_KEY` 即启用真实意图识别和知识库未命中时的导购兜底。LLM 正文以 100–180 字为目标、最多 180 字，并自动显示“回答由AI生成”；未配置或调用失败时回复“请咨询客服”，不显示转接按钮。
- **损坏扣费图**：划痕、磕碰、镜片和维修赔付问题会展示业务方提供的标准图；最终类型、尺寸和金额以归还验收与客服确认为准。
- **实时物流**：当前只展示商家手工录入的承运商和运单号，不生成虚假位置或预计送达时间。接入选定的物流服务与凭证后再启用实时轨迹。
- **提醒通道**：当前为站内事件、订单页即时补齐与 60 秒轮询；Vercel Hobby Cron 每天批处理一次。短信、邮件和微信主动通知尚未接入。
- **异地归还**：当前提供腾讯地图搜索附近顺丰服务点的入口，不代表猫猫头自营归还网点，寄出前需与人工确认。
- **客服口径确认**：首批 FAQ 已按业务方提供的原文纳入；其中租期、逾期费、多处损坏计算与旧 PRD/Spec 有少量冲突，正式上线前需统一口径。
- **飞书同步**：将 `.env` 中 `FEISHU_ENABLED=true` 并填入 App ID/Secret/多维表格 token 后启用；`app/integrations/feishu.py` 的轮询回流逻辑待凭证就绪后补完。
- **季节折扣日历**：`app/core/business_rules.py` 的 `SEASONAL_DISCOUNT` 目前仅 9 月示例，待业务方提供完整年度日历。
- **赔偿区间**：`business_rules.py` 已按左开右闭整理，待业务方对照实物习惯最终确认。
- **生产加密**：`core/security.py` 为占位实现，生产应替换为 `cryptography` 的 AES-256-GCM。
