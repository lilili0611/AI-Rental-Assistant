# 猫猫头相机租赁 AI 助手系统 — 技术规格文档 (Spec)

| 项目 | 内容 |
|------|------|
| 文档类型 | Technical Specification |
| 版本 | v2.10.5 |
| 状态 | Phase 1+2 与 v2.1–v2.10 已实现；v2.10.5 增加租客终态订单删除 |
| 配套文档 | 《产品需求文档 (PRD) v2.10.5》 |
| 范围 | Phase 1–2 详细规格 + Phase 3–4 接口预留 |

---

## 0. v2.0 实现现状与变更 (开发必读)

> **铁律：每次迭代必须先更新 PRD 和本 Spec，再改代码。**
> 已落地代码结构（FastAPI）：`app/{models,schemas,services,api,intent,integrations,core}`、前端 `app/static/index.html`、种子 `scripts/seed_data.py`、测试 `tests/`(pytest) + `tests-e2e/test.js`(Playwright)。仓库 https://github.com/lilili0611/AI-Rental-Assistant 。

**相对 v1.0 的关键落地差异：**

1. **技术栈实际**：DB 用 **SQLite**(`sqlite:///./rental.db`，架构可迁移 PostgreSQL)；LLM 用 **DeepSeek**(OpenAI 兼容，`/chat/completions`，无 Key 时降级关键词规则)；定时任务用 **APScheduler**(替代 Celery+Redis)，每分钟扫预留过期与订单超时、每30秒飞书轮询；会话存储为进程内 `InMemorySessionStore`(接口化，可换 Redis)；敏感字段加密为占位实现(生产换 AES-256-GCM)。
2. **定价模型变更**：见 §5.2，档位计价取代折扣模型。`camera_configs` 字段随之变更，见 §2.3。
3. **认证(MVP 历史)**：早期 `POST /api/auth/login {phone}` 返回 user_id；**v2.4 已改为租客邮箱密码登录 + HttpOnly Cookie 会话**，旧手机号直登迁到 `/api/auth/phone-login` 仅作兼容。
4. **新增 API**：见 §4.7（auth/login、confirm-payment、advance、前端托管）。
5. **飞书双向同步已实现**：见 §7（含飞书→AI 回流与务实冲突策略）。
6. **角色**：简化三级 customer/staff/admin（is_staff 判定含 sales/warehouse/finance/service 以便扩展）。

---

## 0.1 v2.1 变更 (订单审核 / 物流 / 商家验收 / 商家管理页)

> 对应 PRD v2.1 §0.1。**设计原则：内部状态机不变，只加映射层与少量字段/接口。**

落地清单：

1. **客户可见标签映射层**（§3.1）：内部状态 → 中文标签，前端只展示标签，不改 `orders.status` 取值。
2. **`orders` 新增字段**：`carrier`（快递公司）、`tracking_no`（物流单号）。见 §2.5。
3. **状态机新增转换 `shipped → completed`**（商家验收），跳过 `active/returned`。后两者定义保留兼容旧数据。见 §3.1。
4. **商家审核合并接口** `POST /api/orders/{id}/review`：approve 一步完成 `pending_payment→paid→confirmed` 并记录收款；reject 留在 `pending_payment` 附原因。见 §4.8。
5. **发货接口** `POST /api/orders/{id}/ship`：写 `carrier/tracking_no` 并 `confirmed→shipped`。**验收接口** `POST /api/orders/{id}/accept`：`shipped→completed`。见 §4.8。
6. **商家管理页** `GET /admin`：staff 专用静态页（`app/static/admin.html`）。见 §4.8。
7. **飞书**：字段映射新增「快递公司」「物流单号」两列；状态归一表补 v2.1 标签。见 §7。

---

## 0.2 v2.2 变更 (商家后台密码鉴权 + 生产部署)

> 对应 PRD v2.2 §0.2。**设计原则：只收紧 B 端入口，租客 C 端流程不变。**

落地清单：

1. **`users` 新增 `password_hash`**（仅 staff/admin 设置；PBKDF2 加盐哈希，不存明文）。见 §2.1。
2. **`core/security.py` 新增**口令哈希 + 会话令牌工具：`hash_password` / `verify_password` / `make_token` / `verify_token`（HMAC-SHA256 签名，含有效期，密钥用 `ENCRYPTION_KEY`，**纯标准库**）。见 §10。
3. **新增 `POST /api/auth/staff-login`**：手机号 + 密码 → 校验角色与口令 → 返回 `token`。见 §4.9。
4. **新增依赖 `get_staff_user`**：从 `Authorization: Bearer <token>` 解析并校验令牌 + 角色。见 §4.9。
5. **B 端接口改鉴权**：`/review` `/ship` `/accept` `/orders/admin` `/confirm-payment` `/advance` 改用 `get_staff_user`（凭 token，而非可伪造的 `X-User-Id`）。见 §4.9。
6. **`admin.html`**：登录改为手机号 + 密码，保存 token，请求头带 `Authorization: Bearer`。
7. **设置密码脚本** `scripts/set_staff_password.py`；`seed_data` 给演示员工设默认密码并打印提示。
8. **生产部署**：`deploy/` 目录（Nginx / systemd / `.env.production.example`）+ 部署手册。见 §11。

---

## 0.3 v2.3 变更 (数据库迁移到 Supabase / Postgres)

> 对应 PRD v2.3 §0.3。**核心结论：以连接配置 + 驱动为主，业务代码不重写**（ORM 早已 DB 无关）。

落地清单：

1. **驱动**：`requirements.txt` 增加 `psycopg[binary]`（psycopg3）；连接串用 `postgresql+psycopg://`。
2. **引擎**：`app/database.py` 已对非 SQLite 不传 `check_same_thread`，并 `pool_pre_ping=True`；为 Postgres 增加 `pool_recycle`（避免连接被 Supabase 池回收后报错）。见 §1.3。
3. **配置**：`DATABASE_URL` 指向 Supabase 连接串（推荐用 Pooler/IPv4，含 `sslmode=require`）。本地 SQLite 仅用于单测与可选本地开发。
4. **建表**：沿用启动时 `Base.metadata.create_all`；首次连 Supabase 即建好全部表（结构同 §2）。JSON 字段在 PG 落 JSON。
5. **数据迁移**：新增 `scripts/migrate_sqlite_to_pg.py`，按外键依赖顺序（`Base.metadata.sorted_tables`）把本地 SQLite 行复制到 `DATABASE_URL` 目标库；可选 `--truncate` 先清空目标。或用 `scripts/seed_data.py` 直接对 Supabase 灌干净目录。
6. **测试**：`tests/conftest.py` 维持内存 SQLite，不连真实库；迁移正确性单独用「SQLite→SQLite 临时库」验证复制逻辑。
7. **安全**：连接串只进环境变量/`.env`，不入库；`deploy/.env.production.example` 与 `.env.example` 给出 Supabase 示例。

---

## 0.4 v2.4 变更 (租客邮箱账号密码认证)

1. **`users` 新增 `email`**：租客使用邮箱 + 密码注册/登录；`email` 唯一索引，历史库启动时自动补列。
2. **新增 `POST /api/auth/register`**：邮箱 + 密码 + 可选昵称 → 创建 customer，密码 PBKDF2 加盐哈希存储，写入 HttpOnly 会话 Cookie。
3. **`POST /api/auth/login` 改为租客邮箱密码登录**：登录成功写入 HttpOnly 会话 Cookie。
4. **C 端接口改鉴权**：订单创建/查询/修改/取消改为 `get_current_user` 校验 `customer_session` Cookie，不再接受可伪造的 `X-User-Id`。
5. **兼容接口**：旧手机号直登迁到 `/api/auth/phone-login`，仅保留给本地演示/旧脚本，不作为正式前端入口。
6. **B 端不变**：商家后台仍使用 `/api/auth/staff-login`（手机号 + 密码）。

---

## 0.5 v2.5 变更 (订单超时自动取消)

1. **客户未付款超时**：`pending_payment` 且 `paid_amount=0` 的订单，下单超过 1 小时自动取消并释放库存。
2. **商家未处理超时**：已录入收款但仍未确认档期的订单，超过 12 小时自动取消并释放库存；该场景不收手续费，已收金额全额退回。
3. **定时任务**：APScheduler 每分钟扫描一次超时订单；自动取消写入 `order_changes` 审计，原因区分「客户未付款」与「商家未处理」。
4. **配置项**：`UNPAID_ORDER_TTL_HOURS=1`，`MERCHANT_REVIEW_TTL_HOURS=12`。

---

## 0.6 v2.6 变更 (押金仅展示 + 商家修改租金)

1. **金额口径**：`total_price` 表示应付租金，不含押金；`deposit_amount` 只用于展示押金参考。
2. **线下收款**：租金不通过平台支付；商家在后台记录 `paid_amount` 和 `payment_note`。
3. **商家改租金**：新增 `POST /api/orders/{id}/rent`，允许 staff/admin 在商家审核中修改最终租金。
4. **审核通过**：`POST /api/orders/{id}/review` 支持 `rent_amount`，可在审核通过时同步修改最终租金并记录已收租金；已收金额不得低于最终租金。

---

## 阅读指南

本文档定义系统的技术实现规格,供开发直接落地。包含:数据模型(字段级)、API 契约(请求/响应级)、状态机、核心算法。

**与 PRD 的分工:** PRD 说"做什么",本文档说"怎么做"。业务规则的来源以 PRD 第 3 章为准,本文档只定义其技术实现。

**标注约定:**
- 🔴 **修正项** — 与前期代码不同,需重新实现
- ⚠️ **待确认** — 依赖 PRD 待决策项,确认后才能最终定稿

---

## 1. 技术架构

### 1.1 技术栈

| 层 | 技术 | 版本 |
|----|------|------|
| Web 框架 | FastAPI | 0.104+ |
| ORM | SQLAlchemy | 2.0+ |
| 数据库 | PostgreSQL | 15+ |
| 缓存 / 会话 | Redis | 7+ |
| 异步任务 | Celery | 5+ |
| 数据验证 | Pydantic | 2.0+ |
| 飞书集成 | Lark SDK | 官方最新 |

### 1.2 分层结构

```
API 层 (路由、请求校验、权限)
  ↓
Service 层 (业务逻辑、事务)
  ↓
Model 层 (ORM、数据持久化)
  ↓
PostgreSQL + Redis
```

外部集成(飞书、快递、短信、LLM)通过独立的 integration 模块封装,Service 层调用。

---

## 2. 数据模型 (字段级)

所有表统一带 `created_at` / `updated_at` 时间戳。主键 UUID 用 `uuid4`,业务可读 ID(订单号)单独生成。

### 2.1 users — 用户

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 主键 |
| phone | VARCHAR(20) | UNIQUE, NOT NULL, INDEX | 手机号；商家后台登录标识；邮箱租客为内部占位 |
| email | VARCHAR(255) | UNIQUE, INDEX, NULL | 🆕 v2.4 租客邮箱登录标识 |
| name | VARCHAR(100) | | 姓名 |
| is_authenticated | BOOLEAN | DEFAULT false | 是否完成实名认证 |
| id_number_encrypted | VARCHAR(255) | NULL | 身份证号(AES-256 加密) |
| address_encrypted | VARCHAR(255) | NULL | 地址(加密) |
| role | VARCHAR(20) | DEFAULT 'customer' | customer/sales/warehouse/finance/admin |
| credit_score | INTEGER | DEFAULT 100 | 信用分 |
| password_hash | VARCHAR(255) | NULL | 🆕 v2.2 后台登录口令(PBKDF2 加盐哈希)；仅 staff/admin 设置 |

> ⚠️ `role` 的取值范围取决于 PRD 待决策项 1(权限模型)。若 Phase 1 简化,则只有 customer/staff/admin 三值。

### 2.2 cameras — 设备

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(20) | PK | 设备 ID,如 "R5" |
| name | VARCHAR(100) | NOT NULL, INDEX | 设备名 |
| brand | VARCHAR(50) | | 品牌 |
| model | VARCHAR(100) | | 型号 |
| daily_price | NUMERIC(10,2) | | 默认日租金(参考) |
| deposit_amount | NUMERIC(10,2) | | 默认押金(参考) |
| knowledge_entry_id | VARCHAR(100) | NULL | 关联 RAG 知识库(Phase 3) |

> 🔴 **修正**:库存字段(total/rented/reserved)从 `cameras` 和 `camera_configs` 中**移除**。库存不再是设备上的静态计数,而是由占用表按日期动态计算(见 2.4)。设备表只保留设备元信息和参考价。

### 2.3 camera_configs — 设备配置

同一设备的不同配置独立计库存,是库存的实际管理单元。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 配置 ID |
| camera_id | VARCHAR(20) | FK→cameras.id, INDEX | 所属设备 |
| config_name | VARCHAR(200) | NOT NULL | 如 "R5 + 16-35mm" |
| total_units | INTEGER | NOT NULL | **该配置的实物总台数** |
| two_day_price | NUMERIC(10,2) | NOT NULL | 🔴 两天租金 |
| three_day_price | NUMERIC(10,2) | NOT NULL | 🔴 三天租金 |
| extra_day_price | NUMERIC(10,2) | NOT NULL | 🔴 三天以上续租单价(元/天) |
| deposit_amount | NUMERIC(10,2) | NOT NULL | 该配置押金 |
| accessories | JSONB | DEFAULT '[]' | 配件列表 |

> 🔴 **v2.0 变更**：`daily_price` 移除，改为三档价格(见 §5.2 档位计价)。`cameras.daily_price` 保留但语义改为列表展示用的"两天起"价。

> 🔴 **修正**:用 `total_units`(实物总数,静态)替代原来的 current/rented/reserved 计数。某一天的可用数 = total_units − 该天的占用数,占用数由 2.4 的占用表实时算出。

### 2.4 inventory_units — 库存单元 (新增) 🔴

为正确实现按日期的库存,引入"库存单元"概念:每一台实物设备是一个 unit,占用记录挂在 unit 上。

**方案 A(推荐,精确):** 为每台实物建 unit,占用精确到具体哪一台。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | 单元 ID |
| config_id | UUID | FK→camera_configs.id, INDEX | 所属配置 |
| unit_label | VARCHAR(50) | | 实物编号/序列号 |
| status | VARCHAR(20) | DEFAULT 'available' | available/maintenance/retired |

**occupancy — 占用记录 (新增):**

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | |
| config_id | UUID | FK, INDEX | 配置(冗余,便于查询) |
| unit_id | UUID | FK→inventory_units.id, NULL | 具体占用的台(可后绑定) |
| occupancy_type | VARCHAR(20) | | reservation / order |
| start_date | DATE | NOT NULL, INDEX | 占用起始日 |
| end_date | DATE | NOT NULL, INDEX | 占用结束日 |
| ref_id | VARCHAR(36) | | 关联的预留 ID 或订单 ID |
| expires_at | TIMESTAMP | NULL | 预留占用的过期时间 |
| status | VARCHAR(20) | DEFAULT 'active' | active/released/expired |

> 🔴 这是修正库存逻辑的核心结构。"某配置在 [start, end] 区间是否有 N 台可用"的查询,转化为:对区间内每一天,统计该天 active 的 occupancy 数,确认 `total_units − 占用数 ≥ N`。算法见第 5 章。

> ⚠️ **待确认**:方案 A(精确到台)适合需要管理具体设备序列号的场景;若业务上不区分具体哪台、只关心数量,可用更轻的**方案 B**(只在 occupancy 表记数量,不建 unit 表)。请评审时确认是否需要追踪到具体台。

### 2.5 orders — 订单

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | VARCHAR(30) | PK | 订单号,如 ORD20240601001 |
| user_id | UUID | FK→users.id, INDEX | 下单客户 |
| status | VARCHAR(30) | DEFAULT 'draft' | 见 3.1 状态机 |
| subtotal | NUMERIC(10,2) | | 租金小计 |
| deposit_amount | NUMERIC(10,2) | | 展示押金(不计入应付) |
| discount_amount | NUMERIC(10,2) | DEFAULT 0 | 优惠抵扣 |
| total_price | NUMERIC(10,2) | | 应付租金(不含押金) |
| paid_amount | NUMERIC(10,2) | DEFAULT 0 | 已收金额(人工录入) |
| payment_note | VARCHAR(500) | NULL | 🔴 支付凭证备注(人工填) |
| rental_start | DATE | NOT NULL | 租期起 |
| rental_end | DATE | NOT NULL | 租期止 |
| created_by | UUID | | 创建者 |
| version | INTEGER | DEFAULT 1 | 乐观锁版本号 |
| source | VARCHAR(20) | DEFAULT 'ai' | ai/feishu/manual |
| last_modified_by | UUID | | 最后修改者 |
| carrier | VARCHAR(50) | NULL | 🆕 v2.1 快递公司(商家手填) |
| tracking_no | VARCHAR(100) | NULL | 🆕 v2.1 物流单号(商家手填,前端展示) |
| review_note | VARCHAR(500) | NULL | 🆕 v2.1 审核备注/驳回原因 |
| customer_deleted_at | DATETIME | NULL | 🆕 v2.10.5 租客侧删除时间；非空时 C 端列表隐藏，B 端保留 |

> 🆕 **v2.1**:`carrier`/`tracking_no` 在发货(`/ship`)时写入,前端只读展示,不对接快递 API。`review_note` 记录审核驳回原因。收款金额仍复用 `paid_amount`/`payment_note`。

> 🔴 **修正**:移除任何"支付二维码""支付通道"相关字段。新增 `payment_note` 记录人工收款凭证(如转账流水号、收款方式)。`paid_amount` 由财务/销售手动确认收款后填写。

### 2.6 order_items — 订单明细

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | |
| order_id | VARCHAR(30) | FK→orders.id | |
| camera_config_id | UUID | FK→camera_configs.id | |
| quantity | INTEGER | DEFAULT 1 | 数量 |
| price_per_day | NUMERIC(10,2) | | 下单时锁定的日价 |
| discount_rate | NUMERIC(5,3) | DEFAULT 1.0 | 综合折扣率 |
| subtotal | NUMERIC(10,2) | | 该明细小计 |

### 2.7 reservations — 预留

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | |
| user_id | UUID | INDEX | |
| camera_config_id | UUID | FK | |
| quantity | INTEGER | | |
| rental_start | DATE | | 🔴 预留也要带日期区间 |
| rental_end | DATE | | |
| expires_at | TIMESTAMP | NOT NULL | 创建 + 30 分钟 |
| status | VARCHAR(20) | DEFAULT 'active' | active/confirmed/expired/cancelled |
| order_id | VARCHAR(30) | FK, NULL | 转单后关联 |

> 🔴 **修正**:预留必须带 `rental_start`/`rental_end`,否则无法在占用表中正确登记日期区间。前期代码的预留缺少日期。

### 2.8 conversations — 对话记录

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | |
| session_id | UUID | INDEX | 会话 ID |
| user_id | UUID | FK, NULL | 匿名查询可为空 |
| round_number | INTEGER | | 轮次 |
| user_message | VARCHAR(1000) | | 用户输入 |
| ai_response | VARCHAR(2000) | | AI 回复 |
| detected_intent | VARCHAR(50) | | 识别意图 |
| intent_confidence | NUMERIC(5,3) | | 置信度 |
| entities | JSONB | | 提取的参数 |

### 2.9 order_changes — 订单变更审计

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | |
| order_id | VARCHAR(30) | FK, INDEX | |
| change_type | VARCHAR(20) | | create/update/cancel/return |
| changed_by | UUID | | 操作者 |
| changed_at | TIMESTAMP | INDEX | |
| old_value | JSONB | | 变更前快照 |
| new_value | JSONB | | 变更后快照 |
| reason | VARCHAR(500) | NULL | 变更原因 |

### 2.10 user_addresses — 用户地址

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | UUID | PK | |
| user_id | UUID | FK, INDEX | |
| address_type | VARCHAR(20) | | shipping/billing |
| province / city / district | VARCHAR(50) | | 省市区 |
| detail_address | VARCHAR(500) | | 详细地址 |
| receiver_name | VARCHAR(100) | | 收件人 |
| phone | VARCHAR(20) | | 收件电话 |
| is_default | BOOLEAN | DEFAULT false | 默认地址 |

---

## 3. 状态机

### 3.1 订单状态机

```
draft ──创建──> pending_payment ──人工确认收款──> paid
                      │                              │
              (1h未付款/取消)              (12h未处理/审核)
                      │                              │
                      v                              v
                  cancelled                      confirmed
                                                     │
                                                  仓库发货
                                                     │
                                                     v
                                                  shipped
                                                     │
                                                  客户签收
                                                     │
                                                     v
                                                  active
                                                     │
                                                  客户归还
                                                     │
                                                     v
                                                  returned ──验收对账──> completed
```

**状态定义与转换规则:**

| 状态 | 含义 | 可转入 | 触发者 |
|------|------|--------|--------|
| draft | 草稿,未提交 | pending_payment, cancelled | 系统/客户 |
| pending_payment | 待支付 | paid, cancelled | — |
| paid | 已确认收款 🔴 | confirmed, cancelled | 财务(人工) |
| confirmed | 已审核 | shipped, cancelled | 销售/管理员 |
| shipped | 已发货 | **completed** 🆕 / active | 仓库 |
| active | 使用中 | returned | 客户签收触发 |
| returned | 已归还待验收 | completed | 仓库 |
| completed | 已完成 | — | 系统/商家验收 |
| cancelled | 已取消 | — | 多角色 |

> 🆕 **v2.1**:新增 `shipped → completed`(商家验收 `/accept`),默认流程跳过 `active/returned`。`active/returned` 仍保留,供旧数据及未来需要客户签收/归还的场景使用。

> 🔴 **关键修正**:`pending_payment → paid` 的转换由**人工确认收款**触发,不是支付回调。`paid` 状态记录 `paid_amount` 和 `payment_note`。

### 3.1.1 客户/商家可见标签映射 🆕 v2.1

前端与商家管理页**不直接展示 `status` 英文值**,统一经下表映射为中文标签(单一事实来源,前后端共用):

| 内部 status | 客户可见标签 | 商家管理页可执行操作 |
|------------|-------------|---------------------|
| pending_payment | 商家审核中 | 审核通过 / 审核驳回 |
| paid | 商家审核中 | (过渡态,review 内自动推进到 confirmed) |
| confirmed | 已确认档期（待发货） | 上传物流并发货 |
| shipped | 已发货（附快递公司+物流单号） | 商家验收 |
| active | 使用中（旧数据兼容） | 商家验收 |
| returned | 待验收（旧数据兼容） | 完结 |
| completed | 订单已完结 | — |
| cancelled | 已取消 | — |

> 审核驳回不改 status(仍 pending_payment),仅写 `review_note`,客户标签可加注"（审核未通过：<原因>）"。

**取消规则的状态约束:**
- `pending_payment` 且 `paid_amount=0`:客户未付款超过 1 小时,系统自动取消并释放占用
- 已录入收款但未确认档期:商家超过 12 小时未处理,系统自动取消并释放占用;不收手续费,已收金额全额退回
- 客户/人工取消 `pending_payment`:免费,释放占用
- 客户/人工取消 `paid`/`confirmed`:扣 10% 手续费,退余额
- `shipped` 及之后:不可直接取消

### 3.2 预留状态机

```
active ──转为订单──> confirmed
   │
   └──30分钟超时──> expired (释放占用)
   │
   └──用户取消──> cancelled (释放占用)
```

后台 APScheduler 定时任务每分钟扫描 `expires_at < now()` 且 `status='active'` 的预留,置为 expired 并释放对应 occupancy；同时扫描超时订单并自动取消释放占用。

---

## 4. API 契约

所有 API 前缀 `/api`。返回统一结构,错误返回 `{ "error": str, "details": str, "error_code": str }`。

### 4.1 设备 API (Phase 1)

#### GET /api/cameras

查询设备列表。

**请求参数(Query):**

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| page | int | 否 | 1 | 页码,≥1 |
| limit | int | 否 | 20 | 每页,1–100 |
| search | string | 否 | — | 名称/品牌模糊搜索 |
| brand | string | 否 | — | 品牌筛选 |

**响应 200:**

```json
{
  "data": [
    {
      "id": "R5",
      "name": "Canon EOS R5",
      "brand": "Canon",
      "daily_price": 300.00,
      "deposit_amount": 2000.00
    }
  ],
  "pagination": { "total": 3, "page": 1, "limit": 20, "pages": 1 }
}
```

> 🔴 响应中移除了 available_count 等库存字段 —— 列表页不挂库存,因为库存依赖日期。需要库存时调用库存 API 传日期。

#### GET /api/cameras/{camera_id}

设备详情,含配置列表。

**响应 200:**

```json
{
  "id": "R5",
  "name": "Canon EOS R5",
  "brand": "Canon",
  "specs": { "megapixels": 45, "video": "8K 60fps" },
  "configurations": [
    {
      "id": "uuid",
      "config_name": "R5 + 16-35mm",
      "daily_price": 300.00,
      "deposit_amount": 2000.00,
      "total_units": 3,
      "accessories": ["EF 16-35mm f/2.8L II"]
    }
  ]
}
```

**错误:** 404 设备不存在。

#### GET /api/cameras/{camera_id}/configs

返回该设备所有配置(结构同上 configurations 数组)。

### 4.2 库存 API (Phase 1) 🔴

#### GET /api/inventory/available

查询日期区间内的可用库存。**核心接口,按日期计算。**

**请求参数(Query):**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| start_date | date | 是 | 租期起(YYYY-MM-DD) |
| end_date | date | 是 | 租期止 |
| camera_config_id | UUID | 否 | 指定配置,不填则查全部 |

**响应 200:**

```json
{
  "query": { "start_date": "2024-09-01", "end_date": "2024-09-03" },
  "results": [
    {
      "config_id": "uuid",
      "config_name": "R5 + 16-35mm",
      "total_units": 3,
      "min_available_in_range": 2,
      "daily_breakdown": [
        { "date": "2024-09-01", "available": 2 },
        { "date": "2024-09-02", "available": 2 },
        { "date": "2024-09-03", "available": 3 }
      ]
    }
  ]
}
```

> 🔴 `min_available_in_range` 是区间内每日可用数的**最小值** —— 这才是"整个租期能租几台"的正确答案。前期代码用全局计数,会给出错误结果。

**校验:** start_date > end_date 返回 400。

#### GET /api/inventory/{config_id}/status

查询某配置当前(今日)的库存快照。返回 total_units 和今日 available。

### 4.3 价格 API (Phase 1)

#### GET /api/pricing/calculate

计算租赁价格。

**请求参数(Query):**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| camera_config_id | UUID | 是 | 配置 ID |
| start_date | date | 是 | 租期起 |
| end_date | date | 是 | 租期止 |
| coupon_code | string | 否 | 优惠券(Phase 4) |

**响应 200:**

```json
{
  "device": "R5 + 16-35mm",
  "rental_period": { "start_date": "2024-09-01", "end_date": "2024-09-03", "days": 3 },
  "pricing": {
    "daily_price": 300.00,
    "subtotal": 900.00,
    "day_discount": 1.0,
    "seasonal_discount": 0.9,
    "subtotal_after_discount": 810.00,
    "coupon_discount": 0,
    "final_price": 810.00
  },
  "deposit": 2000.00,
  "total_due": 810.00
}
```

> `deposit` 仅展示，不计入 `total_due`，也不要求租客通过平台支付。

**计算逻辑见第 5 章。校验:** 租期 < 1 天返回 400。

### 4.4 对话 API (Phase 1 单轮 / Phase 2 多轮)

#### POST /api/chat

**请求体:**

```json
{ "session_id": "uuid 或 null", "message": "R5 租 7 天多少钱?" }
```

**响应 200:**

```json
{
  "session_id": "uuid",
  "round": 1,
  "detected_intent": "pricing_query",
  "confidence": 0.95,
  "ai_response": "R5 + 16-35mm 租 7 天...",
  "next_actions": [ { "type": "button", "label": "立即下单", "action": "order_create" } ]
}
```

Phase 1:无 session_id 即新建,单轮返回,不存上下文到 Redis。
Phase 2:维护会话上下文(见第 6 章)。

### 4.5 订单 API (Phase 2)

#### POST /api/orders

创建订单。需认证。

**请求体:**

```json
{
  "items": [ { "camera_config_id": "uuid", "quantity": 1 } ],
  "rental_start": "2024-09-01",
  "rental_end": "2024-09-03",
  "shipping_address": {
    "receiver_name": "张三",
    "phone": "13800138000",
    "province": "江西省",
    "city": "南昌市",
    "district": "西湖区",
    "detail_address": "丁公路北 88 号 2 栋 301"
  },
  "reservation_id": "uuid 可选"
}
```

**响应 201:**

```json
{
  "order_id": "ORD20240601001",
  "status": "pending_payment",
  "total_price": 810.00,
  "deposit": 2000.00,
  "payment_instruction": "请通过线下转账完成支付,并联系客服确认",
  "reservation_expires_at": "2024-09-01T12:30:00Z"
}
```

> 🔴 响应中是 `payment_instruction`(人工支付引导文案),不是支付二维码。

**错误:** 422 库存不足(附 details 说明哪天不够)。

#### PATCH /api/orders/{order_id}

修改订单(改期/改量)。需认证,只能改自己的订单。携带 `version` 做乐观锁。

**请求体示例(延期):**

```json
{ "action": "extend", "new_end_date": "2024-09-10", "version": 1 }
```

**响应 200:** 返回新价格、差额、新版本号。version 不匹配返回 409 冲突。

#### DELETE /api/orders/{order_id}

取消订单。按 3.1 的取消规则计算手续费。

**响应 200:**

```json
{ "order_id": "...", "status": "cancelled", "refund_amount": 729.00, "cancellation_fee": 81.00 }
```

#### GET /api/orders

查询当前用户订单列表。支持 status、page、limit 筛选；自动排除 `customer_deleted_at IS NOT NULL` 的订单。

#### DELETE /api/orders/{order_id}/record

从当前租客的“我的订单”删除终态订单。仅允许 `cancelled/completed`，仅订单本人可操作，查询参数 `version` 用于乐观锁。

**响应 200：** `{ "order_id": "...", "deleted": true, "version": 3 }`。

该接口只写 `customer_deleted_at`、递增 `version` 并新增 `order_changes.change_type="customer_delete"`；不物理删除订单，不改变 `status`，不触发库存、退款或飞书同步。重复请求幂等成功；进行中订单返回 `order_not_deletable`。

### 4.6 飞书同步 (Phase 2,内部接口)

不对外暴露 HTTP,由 Service + APScheduler 实现(替代 Celery)。详见第 7 章。

### 4.7 v2.0 新增 API

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/auth/register` | 🆕 租客邮箱 + 密码注册，写入 HttpOnly Cookie | 否 |
| POST | `/api/auth/login` | 🆕 租客邮箱 + 密码登录，写入 HttpOnly Cookie | 否 |
| POST | `/api/auth/logout` | 🆕 租客退出登录，清除 Cookie | 否 |
| POST | `/api/auth/phone-login` | 旧手机号直登，仅本地演示/兼容脚本 | 否 |
| POST | `/api/orders/{id}/confirm-payment` | 🔴 人工确认收款 pending_payment→paid，body: paid_amount/payment_note/version | staff |
| POST | `/api/orders/{id}/advance` | 推进状态机，body: target(confirmed/shipped/active/returned/completed)/version | staff |
| POST | `/api/orders/{id}/rent` | 🆕 商家修改最终租金，押金不计入应付 | staff |
| GET | `/` | 租客自助下单前端单页(`app/static/index.html`) | 否 |
| (mount) | `/static/*` | 静态资源(含吉祥物 mascot.png) | 否 |

- 计价/库存/设备 API 响应随 §2.3/§5.2 调整：配置返回 two_day_price/three_day_price/extra_day_price；`/api/pricing/calculate` 的 pricing 含 basis/rent/三档价/extra_days(不再有 day_discount/seasonal)。
- 前端鉴权：浏览器自动携带 `customer_session` HttpOnly Cookie（FastAPI 依赖 `get_current_user`/`get_optional_user`）。

### 4.8 v2.1 新增 API (订单审核 / 物流 / 验收 / 商家页)

所有 staff 接口使用 `Authorization: Bearer <token>` 鉴权,校验 role ∈ {staff, admin}；均携带 `version` 做乐观锁,不匹配返回 409。

| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/api/orders/{id}/review` | 🆕 商家审核 | staff |
| POST | `/api/orders/{id}/rent` | 🆕 修改订单最终租金 | staff |
| POST | `/api/orders/{id}/ship` | 🆕 上传物流并发货 | staff |
| POST | `/api/orders/{id}/accept` | 🆕 商家验收完结 | staff |
| GET | `/api/orders/admin` | 🆕 商家端订单列表(全部用户,支持 status 筛选/分页) | staff |
| GET | `/admin` | 🆕 商家管理页静态页(`app/static/admin.html`) | staff(页面内校验) |

> 客户列表/详情接口(`GET /api/orders`)响应新增 `display_status`(中文标签)、`carrier`、`tracking_no` 字段。

#### POST /api/orders/{id}/review — 商家审核

一步合并「确认收款 + 放行档期」；可同时修改最终租金。

**请求体:**
```json
{ "approve": true, "rent_amount": 350.00, "paid_amount": 350.00, "payment_note": "微信转账 0613", "version": 1 }
{ "approve": false, "review_note": "未收到款", "version": 1 }
```

- `approve=true`:要求 `status==pending_payment`,可先按 `rent_amount` 更新最终租金；要求 `paid_amount >= total_price`；内部执行 `pending_payment→paid`(写 `paid_amount`/`payment_note`)→`paid→confirmed`,返回新 status=`confirmed`、`display_status="已确认档期（待发货）"`。
- `approve=false`:status 保持 `pending_payment`,写 `review_note`,返回 `display_status="商家审核中（审核未通过：<原因>）"`。

**错误:** 409 version 冲突；422 非法状态(非 pending_payment)。

#### POST /api/orders/{id}/ship — 上传物流并发货

**请求体:**
```json
{ "carrier": "顺丰速运", "tracking_no": "SF1234567890", "version": 2 }
```

- 要求 `status==confirmed`;写 `carrier`/`tracking_no`,执行 `confirmed→shipped`。
- `carrier`、`tracking_no` 必填非空。返回 `display_status="已发货"`。

**错误:** 422 缺物流字段或非法状态；409 version 冲突。

#### POST /api/orders/{id}/accept — 商家验收完结

**请求体:** `{ "version": 3 }`

- 要求 `status==shipped`(兼容 `active`/`returned`);执行 `→completed`。返回 `display_status="订单已完结"`。

**错误:** 422 非法状态；409 version 冲突。

> 上述三个接口均写 `order_changes` 审计,并触发 `_sync_to_feishu` 推送(含新增物流列)。

### 4.9 v2.2 商家后台鉴权

#### POST /api/auth/staff-login — 商家后台登录

**请求体:** `{ "phone": "13900000002", "password": "******" }`

- 按 phone 查用户；要求 `role ∈ {staff, admin, sales, warehouse, finance, service}` 且 `password_hash` 已设置且 `verify_password` 通过。
- 成功返回：`{ "token": "<签名令牌>", "user_id": "...", "name": "...", "role": "..." }`。
- 失败统一返回 401（不区分"用户不存在/密码错误/非员工"，避免信息泄露）。

**会话令牌（token）：** `verify_token` 可解析的 HMAC 签名串，载荷含 `user_id` 与过期时间（默认 12 小时）。无状态，无需服务端存储。

#### 鉴权依赖 get_staff_user

读取请求头 `Authorization: Bearer <token>` → `verify_token` 校验签名与有效期 → 加载用户并确认角色为员工。任一不满足返回 401/403。

**改造**：以下 B 端接口由「`X-User-Id` + `is_staff`」改为依赖 `get_staff_user`（凭不可伪造的 token）：
`/review`、`/ship`、`/accept`、`/orders/admin`、`/confirm-payment`、`/advance`。

> 🔴 **安全要点**：`X-User-Id` 头可被任意伪造。v2.2 后台已改为 token；v2.4 租客 C 端改为邮箱密码登录后的 HttpOnly Cookie 会话，订单接口不再接受 `X-User-Id`。

---

## 5. 核心算法

### 5.1 按日期的库存可用性 🔴

```
函数 get_available(config_id, start_date, end_date):
    total = camera_configs.total_units
    min_available = total
    对 d 从 start_date 到 end_date 的每一天:
        # 统计该天 active 的占用
        occupied = count(occupancy
                         where config_id = config_id
                           and status = 'active'
                           and start_date <= d <= end_date
                           and (expires_at is null or expires_at > now()))
        available_d = total - occupied
        min_available = min(min_available, available_d)
    返回 min_available, 每日明细
```

**可用性判断:** 要租 N 台 → `min_available >= N` 才算有货。

> 🔴 这是修正后的正确逻辑。前期代码的 `total - rented - reserved` 不看日期,会把"9月1日租出"误算成"9月全月不可用"。

### 5.2 价格计算

🔴 **v2.0：档位计价**（取代原折扣模型）。实现见 `services/pricing_service.py`。

```
days = (end_date - start_date).days + 1     # 含起含止: 9/1–9/3 = 3 天

if days <= 2:
    rent = two_day_price                    # 两天档
elif days == 3:
    rent = three_day_price                  # 三天档
else:
    rent = three_day_price + (days - 3) × extra_day_price   # 三天 + 续租

total_due = rent                            # 押金只展示, 不计入应付
```

- 天数确认为**含起含止**(9/1–9/3 = 3 天)。
- 原天数阶梯折扣、季节折扣已废弃(`core/business_rules.py` 仅保留损坏赔偿规则)。
- 订单按配置逐项算 `rent`，订单 `subtotal=Σrent`、`discount_amount=0`、`total_price=subtotal`。商家修改租金时同步更新 `subtotal/total_price`，押金仍保留在 `deposit_amount` 仅作展示。

### 5.3 损坏赔偿计算

输入损坏类型 + 实测尺寸,查赔偿规则表返回扣除比例,扣款 = 押金 × 比例。区间按**左开右闭**处理(见 PRD 3.4 待确认项)。多处损坏取累加,但单类封顶 100%。

> ⚠️ 多处损坏是累加还是取最高,需业务确认。

### 5.4 滞纳金计算

```
overdue_days = max(0, (实际归还日 - rental_end).days)
late_fee = overdue_days × daily_price × 0.10
```

---

## 6. 对话与会话管理 (Phase 2)

### 6.1 会话存储

Redis 存活跃会话,Key = `session:{session_id}`,TTL 30 分钟滑动过期。结构包含:最近 5 轮对话、当前订单草稿上下文、意图序列。完整对话落库到 conversations 表。

### 6.2 意图识别

9 类意图(device_query / device_compare / inventory_query / pricing_query / deposit_query / order_create / order_modify / order_cancel / logistics_query)。

**置信度阈值:**
- > 0.8:直接执行
- 0.6–0.8:请求用户确认("您是想……吗?")
- < 0.6:提示咨询客服

**涉及金钱的操作(下单/改单/取消)即使高置信度也需二次确认。**

### 6.3 权限校验

每个意图标注 `requires_auth`。order_* 系列需认证 + 仅操作本人订单。校验在 API 层用 FastAPI 依赖注入实现。

---

## 7. 飞书双向同步 (Phase 2)

> 🔴 **v2.0 已实现**，代码见 `app/integrations/feishu.py`。用 tenant_access_token 直连飞书多维表格(Bitable) REST API；APScheduler 每 30 秒轮询(替代 Celery)。

### 7.1 同步方向

**AI → 飞书(事件驱动):** `push_order` 做 **upsert**——按主列「订单号」搜索记录，存在则 PUT 更新、否则 POST 新建。仅商家审核通过后的订单(confirmed 及之后)允许推送；待审核/未审核订单不会进入飞书，也不会进入补偿重推队列。失败重试 3 次(指数退避)，仍失败标 `sync_status='sync_pending'`。

**飞书 → AI(轮询):** `poll_changes_job` 每 30 秒分页拉取订单表，把人工在飞书的改动回流到本地(订单状态/已收金额/收款备注)，写 `order_changes` 审计、`source='feishu'`。订单状态文本中英文均可识别(`_STATUS_ALIASES` 归一)。(Webhook 推送留待后续。)

### 7.2 字段映射

| 本地字段 | 飞书列 |
|---------|--------|
| id | 订单号 |
| status | 订单状态 |
| rental_start/end | 租期 |
| total_price | 应付金额 |
| paid_amount | 已收金额 |
| carrier | 快递公司 🆕 v2.1 |
| tracking_no | 物流单号 🆕 v2.1 |
| ... | ... |

### 7.3 冲突解决

🔴 **v2.0 务实策略**（飞书 list records 默认不返回 `last_modified_time`，故未用时间戳裁决）：
- 本地有未推送改动(`sync_status=='sync_pending'`) → **本地优先**，重推飞书，跳过回流；
- 否则飞书值与本地不同 → 视为人工在飞书改动 → **回流更新本地**；
- 同步后两边一致 → 天然**防回环**(下次轮询无差异即不动)。

乐观锁 `version` 仍防 API 侧并发覆盖。

> ⚠️ 若要严格实现 v1.0 的"时间戳后改胜出"，需在飞书表加一列「最后更新时间」(type=1002)，再读 `last_modified_time` 裁决——属后续增强。

### 7.4 字段映射(实际列名)

主列名用户可能改动，FIELD_MAPPING 当前：订单号(主) / 订单状态 / 应付金额 / 已收金额 / 租期开始 / 租期结束 / 收款备注 / 快递公司 🆕 / 物流单号 🆕。租期为文本列(传 ISO 日期字符串)，金额为数字列，快递公司/物流单号为文本列。回流时这两列也纳入「飞书改动→本地」回写(`source='feishu'` 审计)。

> 🆕 **v2.1 容错(实现细节)**：`push_order` 写入前先调 `fields` 接口读取表中**实际存在的列名**(缓存 5 分钟)，只推送存在的列。因此即使飞书表尚未添加「快递公司/物流单号」两列，订单推送也不会因 `FieldNameNotFound` 整条失败——这两列只是被跳过。**要启用物流同步，需在飞书订单表手动新增「快递公司」「物流单号」两个文本列**(列名须与 FIELD_MAPPING 一致)。⚠️ 推送报 `FieldNameNotFound` 多为用户改了列名，先读 fields 接口核对再改 `FIELD_MAPPING`。

---

## 8. Phase 3–4 接口预留

以下仅预留接口轮廓,详细规格待对应 Phase 启动前补充(依赖 PRD 待确认项)。

| 模块 | 预留接口 | 依赖 |
|------|---------|------|
| RAG 问答 | POST /api/chat 内部增强检索 | 已有 52 条 FAQ；向量化仍需设备资料 |
| RBAC | 权限中间件 + 角色管理 API | ⚠️ 需确认角色模型 |
| 监控 | /metrics 端点 + 告警规则 | 🔵 |
| 报表 | GET /api/reports/* | 🔵 |
| 推荐 | GET /api/recommendations | 🔵 |
| 评价 | POST /api/reviews | 🔵 |
| 优惠券 | coupon 校验逻辑接入价格计算 | 🔵 |

---

## 9. 测试要点 (关键路径)

虽然详细测试用例单独成文,但以下是 Spec 层面必须覆盖的关键验证点:

1. **按日期库存** 🔴:验证"9/1-3 租出后,9/5 仍可租""跨天预留正确登记每一天"。这是最易出错、必须重点测的逻辑。
2. **价格叠加折扣**:验证天数折扣 × 季节折扣的乘法正确,边界天数(3/4 天、7/8 天)折扣切换正确。
3. **预留过期释放**:验证 30 分钟后占用自动释放,库存回归。
4. **订单状态机**:验证非法状态转换被拒绝(如 shipped 直接取消)。
5. **乐观锁**:验证并发修改同一订单时 version 冲突被正确拦截。
6. **飞书冲突解决**:验证双向修改时时间戳裁决正确。
7. **支付状态** 🔴:验证人工确认收款流程,确认没有任何自动支付逻辑残留。
8. **商家审核** 🆕 v2.1:验证 `review approve` 一步把 pending_payment 推进到 confirmed 且写入收款；`review reject` 留在 pending_payment 并写 review_note；非 pending_payment 状态调用被拒。
9. **物流与验收** 🆕 v2.1:验证 `/ship` 缺 carrier/tracking_no 被拒、成功后 status=shipped 且字段落库；`/accept` 把 shipped 直接推进到 completed(不经 active/returned)；非法状态被拒。
10. **标签映射** 🆕 v2.1:验证各内部状态映射到正确中文标签,客户列表/详情返回 display_status/carrier/tracking_no。
11. **超时自动取消** 🆕 v2.5:验证未付款 1 小时自动取消并释放库存；已收款但商家 12 小时未处理自动取消、不收手续费并释放库存；未到期订单不取消。

---

## 10. 与前期代码的差异清单 (开发必读)

本节汇总 Spec 相对前期已生成代码需要**修改**的地方:

| # | 前期实现 | 本 Spec 要求 | 优先级 |
|---|---------|-------------|--------|
| 1 | 库存用全局计数 total-rented-reserved | 改为按日期的 occupancy 占用表 | 🔴 高 |
| 2 | cameras/configs 表含库存计数字段 | 移除,改 total_units + 占用表 | 🔴 高 |
| 3 | 订单含支付二维码/支付通道 | 移除,改人工确认 + payment_note | 🔴 高 |
| 4 | 预留无日期区间 | 预留必须带 rental_start/end | 🔴 高 |
| 5 | 库存查询返回全局可用数 | 返回 min_available_in_range + 每日明细 | 🔴 高 |
| 6 | 设备列表挂 available_count | 移除,库存只在库存 API 按日期返回 | 中 |

> 这 6 项是 PRD/Spec 复盘后发现的核心修正点。开始 Phase 1 编码前应先据此调整数据模型和库存逻辑,否则后续返工成本高。

---

## 11. 生产部署 (v2.2，国内云服务器)

> 对应 PRD §0.2。目标：国内「轻量应用服务器」上 24h 在线，Nginx 反代 + HTTPS，进程守护常驻。配套文件见仓库 `deploy/`。

### 11.1 运行形态

- 应用进程：`uvicorn app.main:app --host 0.0.0.0 --port 8000`，**单进程/单 worker**（APScheduler 在进程内跑预留扫描与飞书轮询，多 worker 会重复执行）。
- 进程守护：systemd（`deploy/rental.service`），开机自启 + 崩溃重启。
- 反向代理：Nginx（`deploy/nginx.conf.example`）监听 80/443，转发到 127.0.0.1:8000；HTTPS 证书用免费 ACME（如 acme.sh / certbot）。
- 正式域名：`https://bozipaopao.cn/` 为客户前端，`https://admin.bozipaopao.cn/` 为商家后台。应用会按 Host 自动区分页面，本地仍保留 `/admin` 调试入口。
- 数据库：SQLite 文件放持久目录（如 `/var/lib/rental/rental.db`），由 `DATABASE_URL` 指定；定期备份该文件。量级上来后迁 PostgreSQL（仅改 `DATABASE_URL`）。

### 11.2 环境变量（服务器侧，勿入库）

`deploy/.env.production.example` 为模板。必须设置：`ENCRYPTION_KEY`(强随机，关系到密码哈希与令牌签名)、`DEEPSEEK_API_KEY`、`FEISHU_*`(如启用)、`DATABASE_URL`(持久路径)。

### 11.3 上线前置（不可加速）

1. **ICP 备案**：国内服务器对外开放网站强制备案，管局审核约 2–3 周。
2. **域名**：备案与域名绑定；`bozipaopao.cn`、`www.bozipaopao.cn`、`admin.bozipaopao.cn` 解析到同一服务；HTTPS 证书签发。
3. **安全组/防火墙**：仅放行 80/443（与 22）；不要直接对公网暴露 8000。
4. **改默认口令**：上线前用 `scripts/set_staff_password.py` 重设所有员工密码，删除演示弱口令。

### 11.4 部署步骤(概要)

详见 `deploy/DEPLOY.md`。概要：装 Python 3.9+ 与依赖 → 配置 `.env.production` → 初始化/迁移 DB → 装 systemd 服务并启动 → 配 Nginx + HTTPS → 验证 `/health`、客户前端 `https://bozipaopao.cn/`、商家后台 `https://admin.bozipaopao.cn/`。

---

## 12. Supabase / PostgreSQL (v2.3)

> 对应 PRD §0.3。Supabase = 托管 Postgres，本项目作为正式数据库。

### 12.1 连接串 (DATABASE_URL)

格式：`postgresql+psycopg://<user>:<password>@<host>:<port>/postgres?sslmode=require`

- 从 Supabase 控制台 **Project Settings → Database → Connection string** 取得。
- **推荐用 Connection Pooler（Supavisor）连接串**：提供 IPv4、适配云平台与多连接；常驻服务用 **Session** 模式（端口 5432），无服务器/短连接用 **Transaction** 模式（端口 6543）。
- 必须 `sslmode=require`。密码含特殊字符要 URL 编码。
- ⚠️ 连接串含密码：只进环境变量/`.env`，不入库。

### 12.2 驱动与引擎

- 依赖：`psycopg[binary]`（psycopg3）。
- `app/database.py`：SQLite 才传 `check_same_thread=False`；统一 `pool_pre_ping=True`；Postgres 加 `pool_recycle=1800`（Supabase 池会回收空闲连接）。
- 建表：启动 `Base.metadata.create_all(engine)` 自动创建（结构见 §2）。

### 12.3 数据迁移脚本

`scripts/migrate_sqlite_to_pg.py`：
- 源：本地 SQLite（默认 `rental.db`，`--source` 可改）。
- 目标：`settings.database_url`（运行时设为 Supabase 连接串）。
- 逻辑：`create_all` 目标库 → 按 `Base.metadata.sorted_tables`（外键安全顺序）逐表复制；`--truncate` 先按反序清空目标，便于重跑。
- 用法：`DATABASE_URL=<supabase串> python -m scripts.migrate_sqlite_to_pg --truncate`

### 12.4 验证

- `DATABASE_URL=<supabase串> python -c "from app.database import engine; print(engine.connect())"` 连通性。
- 迁移后比对各表行数；启动应用 `/health` + 前端 `/`（设备列表非空）+ 后台 `/admin` 登录。
- 单元测试不连真实库（内存 SQLite），`pytest -q` 仍应全绿。

---

## 13. v2.7 导购知识问答规格

### 13.1 回答路由

`POST /api/chat` 按以下顺序处理，每条消息只命中一条主路径：

1. **不合理请求检测**：命中后返回 `ai_response="请咨询客服"`、`answer_source="customer_service"`，不提供 action。
2. **客服知识库检索**：命中后原样返回条目答案，`detected_intent="knowledge_qa"`、`answer_source="knowledge_base"`，同时记录 `knowledge_entry_id`。
3. **结构化业务处理**：设备、实时库存、价格、押金和订单意图继续调用原有 Service，`answer_source="business_data"`。
4. **LLM 兜底**：前述路径都无法回答时生成通用导购建议。成功时 `answer_source="llm"`；不可用或失败时提示咨询客服。

### 13.2 知识库

- 源文件：`app/knowledge_base/真实客服问答.md`。
- 启动/首次检索时解析“编号 + 问 + 答”条目，答案保留原始换行和列表。
- 检索采用本地确定性匹配：标准化文本、字符相似度、二元组重合度和场景关键词加权。
- 只有达到最低匹配阈值且与次优结果有足够差距时才算命中；低置信度不得错误返回相近政策。
- 知识库回复不得调用 LLM 润色，确保政策口径可追溯。

### 13.3 LLM 兜底约束

- System Prompt 仅允许提供相机、镜头和拍摄场景的一般建议；不得编造店铺价格、库存、赔偿、信用或履约承诺。
- 正文不得包含 Markdown 或 AI 标记，应用层统一添加 `【回答由AI生成】`。
- 应用层清洗单行文本并执行 180 字硬截断，避免模型不遵守长度指令（v2.9 覆盖旧版 50 字约束）。
- 若模型返回客服提示、空内容或发生异常，最终响应必须是精确文本“请咨询客服”，且不添加 AI 标记。

### 13.4 API 增量字段

`ChatResponse` 新增：

```json
{
  "answer_source": "knowledge_base | business_data | workflow | llm | customer_service"
}
```

该字段用于前端区分可追溯知识、实时业务结果、生成内容和人工兜底。现有字段保持兼容。

### 13.5 安全与测试要求

必须验证：

1. 知识库命中时不调用 LLM，且答案与源条目一致。
2. 川西、演唱会、年会、电商服装等导购场景可被同义表达命中。
3. LLM 正文以 100–180 字为目标、最长 180 字并带统一 AI 标记（v2.9 覆盖旧版 50 字约束）。
4. 不合理请求、LLM 未配置、超时和异常均精确回复“请咨询客服”，且不返回转接按钮。
5. 现有库存、价格、订单状态机与测试全部保持通过。

### 13.6 实现清单

- [x] 纳入并解析 52 条真实客服问答。
- [x] 实现确定性知识检索和不合理请求检测。
- [x] 实现短文本 LLM 兜底与统一来源标记。
- [x] 接入对话编排并持久化知识条目编号。
- [x] 增加单元测试并运行完整测试集。

---

## 14. v2.8 全流程陪伴助手规格

### 14.1 租前导购状态机

导购草稿仅保存在会话上下文，不创建订单、不占用库存：

| 内部阶段 | 必需输入 | 下一阶段 | 用户可见动作 |
|---|---|---|---|
| `discover_scene` | 拍摄场景 | `discover_experience` | 选择旅游/人像/演唱会/视频/日常等 |
| `discover_experience` | 新手/有基础 | `discover_priority` | 选择第一次使用/已有基础 |
| `discover_priority` | 省钱/均衡/画质优先 | `recommendation` | 输出最多 2 个真实在售配置对比 |
| `collect_dates` | 起止日期 | `deposit_choice` | 实时计算库存和档位价格 |
| `deposit_choice` | 需要/不需要免押 | `ready_to_order` | 需要时原样返回 FAQ #1 |
| `ready_to_order` | 已确认配置与租期 | 结束 | 返回 `prefill_order` 前端动作 |

导购上下文写入 `conversations.entities.sales_journey`。进程内会话缺失时，按 `session_id` 读取最近 5 轮对话重建历史和导购草稿。

`ChatAction` 新增可选 `payload`，`prefill_order` 包含 `camera_id`、`config_id`、`start_date`、`end_date`、`quantity`。前端只负责带入表单并查询库存，最终创建订单仍必须由已登录用户点击确认。

### 14.2 陪伴阶段映射

陪伴阶段由订单状态和日期派生，不新增模糊订单状态：

| 订单状态/日期 | 陪伴阶段 | 可见能力 |
|---|---|---|
| pending_payment / paid / confirmed | `pre_rental` | 审核进度、准备清单 |
| shipped 且起租日前 | `in_transit` | 运单、物流状态、预计送达（若有） |
| active，或 shipped 且在租期内 | `in_use` | 快速上手、参数建议、在线答疑 |
| returned，或已超过 rental_end 未完成 | `return_due` | 归还提醒、打包说明、地图入口 |
| completed | `post_rental` | 评价、作品分享 |
| cancelled | `closed` | 不再生成陪伴事件 |

### 14.3 数据模型

`companion_events`：`id`、`order_id`、`user_id`、`event_type`、`title`、`message`、`payload`、`status(unread/read)`、`created_at/updated_at`。唯一约束 `(order_id, event_type)`，重复任务执行时更新同一事件。

`order_feedback`：`id`、`order_id(unique)`、`user_id`、`rating(1..5)`、`comment`、`share_url`、`showcase_allowed(default false)`、时间戳。

### 14.4 API

- `GET /api/orders/{order_id}/companion`：仅订单本人可访问；返回阶段、物流、设备指南、归还信息、未读事件和评价状态。
- `POST /api/orders/{order_id}/companion/events/{event_id}/read`：仅订单本人标记已读。
- `POST /api/orders/{order_id}/feedback`：仅订单本人且订单已完成；同一订单重复提交为更新，不新增重复记录。
- `GET /api/community/showcase`：公开返回已授权展示的作品链接、设备名、评分和脱敏评论，不返回用户身份与联系方式。

### 14.5 事件与副作用

| 条件 | 事件类型 | 副作用 | 幂等键 |
|---|---|---|---|
| shipped/active | `usage_guide` | 生成快速上手入口 | order_id + type |
| shipped | `logistics_ready` | 展示人工运单或外部轨迹 | order_id + type |
| 到期前 1 天或已逾期 | `return_reminder` | 更新提醒文案，不改订单状态 | order_id + type |
| completed | `feedback_invite` | 邀请评价 | order_id + type |
| completed | `share_invite` | 邀请自愿分享 | order_id + type |

同步门：陪伴事件不写飞书、不推进订单、不触发资金操作。订单原有 `confirmed` 之后才允许同步飞书的规则保持不变。

订单 `created_at/updated_at` 由数据库按 UTC 生成；自动超时扫描也使用 UTC naive 基准比较，避免上海时区下新订单被误判为已超时。订单号中的可读日期仍使用业务本地时间。

### 14.6 物流降级

当前 `manual` 提供器只返回承运商、运单号和订单阶段，`current_location`、`estimated_delivery` 为 `null`。前端必须显示“实时轨迹待物流服务接入”，禁止根据发货时间自行估算。外部物流提供器确定后通过稳定接口替换，不改变对外响应结构。

### 14.7 测试与发布清单

- [x] 多轮导购按顺序反问且不重复询问已知信息。
- [x] 推荐只使用数据库中的在售配置，并实时计算库存/租金。
- [x] 免押选择返回 FAQ #1，`prefill_order` 正确带入下单页。
- [x] 会话可从数据库恢复导购草稿。
- [x] 陪伴阶段、提醒幂等、评价 upsert、公开分享脱敏均有测试。
- [x] 客户前端已提供下单带入、陪伴入口、评价与站内轮询。
- [x] 88 项完整测试通过；`bozipaopao.cn` 已发布 v2.8.0，并完成健康检查、5 轮导购、知识指南、安全拦截与前端控制台冒烟测试。

---

## 15. v2.8.1 客服降级与扣费标准图规格

### 15.1 对话降级契约

- 统一兜底常量为 `CUSTOMER_SERVICE_RESPONSE="请咨询客服"`。
- 不合理请求返回 `detected_intent="customer_service"`、`answer_source="customer_service"`、`next_actions=[]`。
- LLM 未配置、失败、超时、返回空文本或主动要求客服确认时，使用相同响应，不返回按钮。
- 删除客户端对 `human_handoff` action 的依赖；业务后台原有人工审核、客服处理能力不受影响。

### 15.2 损坏标准素材

- 静态资源：`/static/damage-fee-standard.jpg`，来源为业务方本次提供的原图。
- 损坏政策命中时返回 `damage_policy` 意图、`knowledge_base` 来源及 `open_url` action：`{"url":"/static/damage-fee-standard.jpg"}`。
- 前端 `open_url` 仅允许 `https://` 外链和本站 `/static/` 路径，禁止任意脚本协议。
- 标准图覆盖划痕掉漆、磕碰磨损、镜片磨损、UV 损坏、性能故障、维修占用及首次拆修。
- 10mm、20mm 等边界在原图中存在包含关系重叠；对话层只展示标准与验收提示，不根据自然语言自动出具最终扣款。

### 15.3 测试与发布

- [x] 客户端不再返回旧咨询文案或转接 action。
- [x] 无法回答、不合理请求和危险故障使用新的客服文案。
- [x] 通用及具体损坏问题均返回可访问的标准图入口。
- [x] 93 项测试、前端脚本检查及本地真实浏览器图片点击验证通过。
- [x] `bozipaopao.cn` 已发布 v2.8.1；健康检查、客服兜底、损坏标准图原图校验及进水边界生产冒烟测试通过。

---

## 16. v2.9 四类咨询入口与意图路由规格

### 16.1 确定性路由

新增 `app/services/consultation_routes.py`，维护唯一的四类路由配置：

| route key | detected_intent | 入口标签 |
|---|---|---|
| `order` | `consult_order` | 下单问题咨询 |
| `deposit` | `consult_deposit` | 免押问题咨询 |
| `claim` | `consult_claim` | 理赔问题咨询 |
| `device` | `consult_device` | 设备选择咨询 |

路由只接受受控的入口标签及“进入 + 入口标签”形式，禁止用“下单”“押金”等宽泛词拦截正常业务查询。命中后清空旧的 `sales_journey` 草稿，返回区域说明及 4 个 `consult_question` 按钮，`answer_source="workflow"`，不得调用 LLM。

每个按钮使用现有 `ChatAction`：

```json
{
  "type": "button",
  "label": "免押需要什么条件？",
  "action": "consult_question",
  "payload": {"route": "deposit", "question": "免押需要什么条件？"}
}
```

客户端点击后继续把 `label` 作为新消息发送；服务端按完整优先级重新判定，因而知识库、业务数据与安全规则仍是唯一答案来源。

### 16.2 编排顺序

`POST /api/chat` 的 v2.9 顺序：

1. 不合理请求检测；
2. 四类一级咨询入口；
3. 损坏标准与设备使用指南；
4. 52 条客服知识库；
5. 知识库未覆盖的主动多轮导购；
6. 结构化设备、库存、价格、押金和订单业务；
7. LLM 安全兜底或“请咨询客服”。

一级路由仅负责导航，不改变二级问题的知识库优先约束。设备选择的二级问题允许进入 `guided_sales`，继续复用场景 → 经验 → 偏好 → 租期 → 免押 → 带入下单状态机。

### 16.3 前端展现

- 初始欢迎语固定为“喵～我是猫猫小助手 🐱 快来咨询我吧”。
- 欢迎语下方使用 2×2 路由按钮；窄屏自适应为单列或两列。
- 每个按钮具有可读编号、明确中文标签、最小高度 44px 和 `type="button"`。
- 动态二级问题继续使用现有聊天 action 渲染和 `onAct` 处理，不打开新页面。

### 16.4 LLM 契约

- Prompt 要求中文单行纯文本，正文目标 100–180 字，绝对不超过 180 字。
- `MAX_LLM_BODY_LENGTH = 180`，清洗后在应用层硬截断；AI 标签不计入正文长度。
- 正文统一由 `mark_ai_generated` 加上 `【回答由AI生成】`。
- 店铺价格、实时库存、物流位置、赔偿、免押资格和履约承诺不得编造；需确认时回复“请咨询客服”。

### 16.5 测试与发布清单

- [x] 四个入口分别返回正确意图、来源和 4 个二级问题。
- [x] 一级入口不调用 LLM，切换入口会清除旧导购草稿。
- [x] 二级知识问题仍优先命中知识库且不调用 LLM。
- [x] LLM 正文硬上限为 180 字并保留统一标记。
- [x] 前端静态脚本和真实浏览器交互通过。
- [x] 103 项完整回归测试通过；`bozipaopao.cn` 已发布 v2.9.0，四类路由、知识库优先、设备反问、扣费标准图和 LLM 180 字上限生产冒烟测试通过。

---

## 17. v2.9.1 咨询问题按钮响应式规格

### 17.1 CSS 契约

动态 `ChatAction` 按钮继续渲染在 `.acts` 容器中，不改 API。仅对 `.acts button` 覆盖全局按钮规则：

- `font-size: 12px`、`line-height: 1.45`；
- `white-space: normal`，长中文使用 `overflow-wrap: anywhere` 与 `word-break: break-word`；
- `max-width: 100%`、`min-width: 0`，任何按钮不得超过所属回复气泡；
- `height: auto`、`min-height: 44px`，换行时允许高度自然增长；
- 文本左对齐，短按钮仍按内容宽度显示。

初始四类一级入口继续使用 `.route-btn`，不受本次动态二级问题规则影响。

### 17.2 验证清单

- [x] 静态测试锁定换行、最大宽度、12px 字号与 44px 最小高度。
- [x] 完整自动化测试与前端脚本语法检查通过。
- [x] 真实浏览器在 375px 和桌面宽度下无横向溢出。
- [x] 104 项测试通过；`bozipaopao.cn` 已发布 v2.9.1，并确认生产页面加载按钮换行与宽度限制规则。

---

## 18. v2.9.2 导购发散问题中断路由规格

### 18.1 状态判定

`sales_guide.is_side_question(message, journey)` 只在以下条件同时成立时返回 `true`：

- `journey.active=true`、`journey.recommended=true`；
- `start_date` 或 `end_date` 尚未收齐；
- 消息不是“继续填写租期”或“重新选择设备”；
- 实体提取未得到 `start_date`、`end_date` 或 `days`；
- 消息包含问句、推荐/比较/参数/场景等发散信号。

命中后设置 `journey.paused=true`，保留已有场景、经验、偏好、推荐配置和库存上下文。该暂停状态随 `sales_journey` 一并写入 `Conversation.entities`，支持 Vercel 多实例恢复。

### 18.2 路由与动作

发散问题继续经过安全检测、损坏/使用知识与 FAQ。知识命中时原样返回，并追加恢复动作；知识未命中时直接执行现有 `_fallback_or_customer_service`，不得再次进入 `sales_guide.process`。

发散问题调用 LLM 时追加专用 System Prompt：只回答当前问题、不索要租期；审美风格、构图、拍摄技巧、一般设备类型和公开型号应基于通用知识直接回答，不得仅因缺少日期而拒答。专用提示不放宽店铺库存、价格、赔偿、信用资格、订单状态和履约承诺的禁止编造规则。

```json
[
  {"type":"button","label":"继续填写租期","action":"guide_choice"},
  {"type":"button","label":"重新选择设备","action":"guide_choice"}
]
```

- “继续填写租期”：清除 `paused`，保留原草稿并再次提示日期格式。
- “重新选择设备”：清空原 `sales_journey`，开启新草稿并询问场景。
- 不合理请求仍只回复“请咨询客服”，不得追加恢复动作。

### 18.3 场景词扩展

`portrait` 场景新增“拍人、拍妹子、人物照、复古人像”。场景匹配按现有字典顺序执行，`portrait` 早于 `daily`，因此“复古人像”优先命中人像。

### 18.4 测试与发布清单

- [x] 日期实体与发散问题判定测试通过。
- [x] LLM 发散回答带统一标记、180 字上限和两个恢复动作。
- [x] FAQ 发散回答不调用 LLM并保留导购草稿。
- [x] 继续/重新选择两条状态转换及数据库恢复测试通过。
- [x] 新增人像同义词测试通过。
- [x] 114 项完整回归通过；生产实测发散回答来源为 `llm`、带统一标记、正文 76 字并返回两个恢复动作，继续与重选状态转换均通过。

---

## 19. v2.9.3 手机端登录区域响应式规格

### 19.1 DOM 与桌面样式

- 邮箱输入框使用 `.login-email`，桌面宽度 190px。
- 密码输入框使用 `.login-password`，桌面宽度 120px。
- 禁止在这两个元素上使用内联 `style="width:..."`，确保媒体查询可以覆盖。
- 大于 600px 时继续使用现有 flex 登录区，不改变桌面端交互顺序。

### 19.2 手机端 CSS 契约

在 `@media(max-width:600px)` 内：

- `.logo` 与 `.login` 均设为 `width:100%`；
- `.login` 使用 `grid-template-columns:repeat(2,minmax(0,1fr))`；
- `.who` 使用 `grid-column:1/-1` 且 `white-space:nowrap`；
- `.login input`、`.login button` 使用 `width:100%`、`min-width:0`；
- 登录区列间距和行间距保持 8px；输入与按钮高度沿用全局 46px。

该布局不依赖 JavaScript，不改变登录/注册 API、认证状态或本地存储。

### 19.3 验证清单

- [x] 静态测试确认无内联登录宽度，并锁定移动端网格规则。
- [x] 320×812、375×812、667×375 和 1280×800 真实浏览器检查通过。
- [x] 各视口 `document.documentElement.scrollWidth <= window.innerWidth`。
- [x] 完整回归与前端脚本语法检查通过。
- [x] 115 项回归通过；`bozipaopao.cn` 已发布 v2.9.3，生产健康检查正常，375×812 视口 `scrollWidth=375` 且全部登录控件可见。

---

## 20. v2.9.4 下单收货地址规格

### 20.1 API 与校验

`POST /api/orders` 将原来由客户端传入的可选 `delivery_address_id` 改为必填 `shipping_address` 对象：

| 字段 | 类型 | 规则 |
|---|---|---|
| `receiver_name` | string | 去首尾空格后 2–100 字符 |
| `phone` | string | `^1[3-9]\\d{9}$` |
| `province` / `city` / `district` | string | 各自去首尾空格后 2–50 字符 |
| `detail_address` | string | 去首尾空格后 5–200 字符 |

Pydantic 在任何数据库写入前完成结构校验。接口用当前登录用户的 `id` 创建 `UserAddress(address_type="shipping")`，再把新地址 `id` 写入 `Order.delivery_address_id`。客户端不得指定任意地址 ID，避免把其他用户地址绑定到订单。

订单创建响应、`GET /api/orders`、`GET /api/orders/{id}` 和员工 `GET /api/orders/admin` 均返回结构化 `shipping_address`，并补充只用于展示的 `full_address`。客户订单接口继续受订单本人权限约束；员工列表继续受 staff/admin 等后台角色令牌约束。

若库存、价格或订单创建失败，当前事务回滚，不能遗留孤立地址。成功后地址作为该订单的发货快照使用；本期没有地址修改接口。

飞书同步门保持不变，v2.9.4 不向 `FIELD_MAPPING` 增加收件人、手机号或地址。只有在业务方确认多维表格列、可见成员权限和个人信息处理范围后，才单独设计地址同步；当前员工通过受后台令牌保护的 `/api/orders/admin` 查看。

### 20.2 前端状态与展示

报价成功后，在金额明细和“立即下单”之间展示 `.shipping-form`：收货人、手机号、省、市、区/县、详细地址。所有输入带 `autocomplete`、`maxlength` 和可访问标签；省市区在桌面端三列、手机端单列。

`placeOrder()` 先执行 `collectShippingAddress()`：缺失字段、手机号格式不符或详细地址过短时停止请求、聚焦第一个错误字段并显示中文提示。请求成功后：

- 成功对话显示订单号、金额、收件人及完整地址；
- 客户“我的订单”在租期与金额下展示“收货：收件人 手机号”和完整地址；
- 商家订单列表新增“收货信息”列，展示同一数据；
- 页面渲染全部经 `esc()` 转义，地址不得通过 `innerHTML` 原样注入。

### 20.3 咨询与导购口径

“下单问题咨询”和“下单流程是什么”在价格确认后增加“填写收货信息”步骤。导购的最终回复改为：带入下单页后核对库存与价格，填写收货人、手机号和完整地址，再由用户确认下单。

### 20.4 实施与验证清单

- [x] Schema、API 地址持久化、事务回滚和双端订单输出完成。
- [x] 客户报价卡地址表单、校验、成功口径与订单列表展示完成。
- [x] 商家列表收货信息列和移动端响应式规则完成。
- [x] 120 项 Schema/API/服务/静态页面/咨询导购回归与前端脚本语法检查通过。
- [x] 320×812、375×812、1280×800 真实浏览器检查无横向溢出；本地下单和员工后台地址展示通过。
- [x] `bozipaopao.cn` 已发布 v2.9.4；健康检查正常，375×812 生产页面 `scrollWidth=375`，六个地址字段及确认按钮均已加载。

---

## 21. v2.9.5 导购一键预填状态机

### 21.1 状态与转换

`sales_journey` 增加：

| 字段 | 类型 | 含义 |
|---|---|---|
| `device_confirmed` | boolean | 消息同时含真实设备实体和完整起止日期，允许跳过场景/经验/偏好反问 |
| `shipping_address` | object | 本次导购已可靠识别的收货字段草稿，可为部分字段 |

转换规则：

```text
collecting_requirements
  ├─ 明确设备 + 完整租期 ─> device_confirmed ─> inventory_checked
  └─ 常规导购 ─> recommended + dates ─────────> inventory_checked
inventory_checked ─> deposit_choice ─> ready_to_prefill
ready_to_prefill ──客户点击按钮──> checkout_form_filled
checkout_form_filled ──客户最终确认──> POST /api/orders
```

`device_confirmed` 只改变导购反问路径，不改变库存不足处理、价格计算、免押询问或最终下单确认。重新选择设备时清除设备、日期和收货草稿；继续租期与发散问题恢复规则保持不变。

### 21.2 收货信息确定性提取

新增规则提取器，不调用 LLM：

- `phone`：`(?<!\\d)1[3-9]\\d{9}(?!\\d)`；
- `receiver_name`：只接受“姓名/收货人/联系人”标签后的 2–20 位中文或间隔点字符；
- 完整地址：接受“地址/收货地址/详细地址”标签后的文本，按普通省份或四个直辖市两类正则拆成 `province/city/district/detail_address`；
- 各轮新字段覆盖同名旧草稿，未识别字段保留；不满足完整地址结构时不得凭常识补齐省市区。

完整草稿必须同时拥有 `receiver_name`、`phone`、`province`、`city`、`district`、`detail_address` 且通过 v2.9.4 长度/手机号规则。含任一收货字段的原始消息通过 `redact_shipping_message()` 变为固定占位文本后，才写入 `session.history` 和 `Conversation.user_message`；结构化草稿仍随 `Conversation.entities.sales_journey` 保存，用于多实例恢复。后续 LLM 只看到占位文本。

### 21.3 动作契约与前端

`prefill_order.payload` 保留 `camera_id`、`config_id`、`start_date`、`end_date`、`quantity`，并在存在可靠字段时增加：

```json
{
  "shipping_address": {
    "receiver_name": "张三",
    "phone": "13800138000",
    "province": "江西省",
    "city": "南昌市",
    "district": "西湖区",
    "detail_address": "丁公路北88号2栋301"
  }
}
```

前端点击动作依次执行：`selCam(camera_id)` → 设置配置/日期/数量 → 将 payload 中存在的收货字段合并到内存 `SHIPPING_DRAFT` → `checkQuote()` → 滚动到 `cfgCard`。完整地址提示“设备、租期和收货信息已带入”；缺失时提示“设备和租期已带入，请在下单页补全收货信息”。按钮动作不得调用 `POST /api/orders`。

### 21.4 同步、权限与验收

- 本功能不创建订单、不占用库存、不写 `UserAddress`，因此不触发订单审计和飞书同步。
- 订单、库存、资金和外部同步状态机保持 v2.9.4 规则。
- [x] 设备+日期直达、常规导购和库存不足分支测试通过。
- [x] 完整/部分/无地址 payload 与跨实例恢复测试通过。
- [x] 原始个人信息脱敏后持久化且不进入 LLM 历史。
- [x] 125 项回归与前端脚本语法通过；静态测试锁定动作顺序、字段白名单和无自动下单。
- [x] 375×812 本地真实浏览器验证设备、日期、报价和六个地址字段正确带入；无地址新流程字段为空且页面无横向溢出。
- [x] `bozipaopao.cn` 已发布 v2.9.5；生产健康检查、设备/日期/报价预填、空地址补填提示和 375px 无横向溢出验证通过。

---

## 22. v2.10.0 移动端 AI 与用户中心规格

### 22.1 前端导航与共享对话

- `max-width:600px` 显示固定底部 `.mobile-ai-dock`，使用 `padding-bottom:calc(... + env(safe-area-inset-bottom))` 为页面内容留位；触控区不小于 48px。
- `#aiPanel` 为移动端全屏对话层，打开时锁定背景滚动，关闭时恢复原滚动位置；桌面端不展示悬浮入口，原 `.chat` 保留。
- `addBub()` 同时渲染 `#msgs` 和 `#aiMsgs`；两处输入统一调用 `send()`，共用 `SESSION`，动态动作按钮调用同一 `onAct()`。
- 长按阈值 350ms：超过阈值后打开对话层并调用语音识别；短按只打开对话层。关闭、页面隐藏或松手时停止识别。

### 22.2 语音识别状态

```text
idle ──用户按住──> requesting_permission ──允许──> listening
  └────────────────────────不支持/拒绝──────────> unavailable
listening ──interim result──> listening（更新文字）
listening ──松手/final result──> submitting ──> idle
listening ──无内容/错误──> idle（保留键盘入口）
```

前端使用 `window.SpeechRecognition || window.webkitSpeechRecognition`，`lang='zh-CN'`、`continuous=false`、`interimResults=true`。只有最终非空文本才进入 `/api/chat`；音频不发送到本站后端、不写数据库。页面明确提示识别能力由浏览器提供且可能调用浏览器厂商云服务。

### 22.3 用户资料模型与 API

`users` 新增可空 `avatar_data TEXT`。启动迁移通过 `ensure_runtime_schema()` 在旧库补列。

| 方法 | 路径 | 请求/响应 | 权限 |
|---|---|---|---|
| GET | `/api/auth/me` | 当前 `user_id/email/name/role/avatar_data` | customer Cookie |
| PATCH | `/api/auth/me` | `name?`、`email?`、`avatar_data?`、`current_password?` | customer Cookie |
| POST | `/api/auth/change-password` | `current_password/new_password` | customer Cookie |

规则：

- 昵称去空格后 1–100 字；邮箱归一化后唯一，变更邮箱必须验证当前密码。
- 头像只接受 `data:image/jpeg|png|webp;base64,...`，解码后不超过 300KB，字段总长不超过 450KB；空字符串表示恢复默认头像。
- 修改密码必须验证当前密码，新密码 8–128 字且不能与当前密码相同；数据库只写 PBKDF2 加盐哈希。
- 所有失败统一返回结构化错误；资料接口仅能修改依赖注入得到的当前用户，不接受 `user_id` 请求参数。
- 资料与头像不触发订单、库存或飞书同步；订单列表继续使用 `GET /api/orders` 的本人过滤。

### 22.4 测试与验收

- [x] API：未登录拒绝、本人资料读取、昵称/头像修改、邮箱改动需当前密码、邮箱冲突、密码校验与哈希更新。
- [x] 前端静态：悬浮入口、独立对话层、Web Speech 降级、共享会话、“我的”页和安全区样式存在。
- [x] 375×812：无横向溢出，悬浮入口不遮挡最终内容，登录后头像入口出现，资料和订单页可用；812×375 横屏同样无溢出。
- [x] `bozipaopao.cn` 已发布 v2.10.0；生产健康检查、头像字段迁移、手机 AI 页、登录头像、“我的”资料与本人订单验证通过，未创建测试订单、未记录测试音频。

---

## 23. v2.10.1 移动端视口修复与猫头入口规格

### 23.1 视口高度与输入法状态

- `max-width:900px` 下所有 `input`/`select`/`textarea` 计算字号不小于 16px，阻止 iOS Safari 的输入聚焦自动放大；viewport 不设置 `maximum-scale` 或 `user-scalable=no`。
- 启动时和 `window.visualViewport` 的 `resize`/`scroll` 事件中，把 `visualViewport.height` 写入 CSS 变量 `--app-height`；不支持时回退到 `window.innerHeight`。
- `.app-panel` 使用 `height:var(--app-height,100dvh)`、`max-width:100vw`、`overflow:hidden`；`.ai-panel-body` 和消息气泡必须允许缩小与长文本换行。
- `send()` 在读取非空文本后对当前输入框执行 `blur()`，然后在两个动画帧及短延时后重算可见高度，使键盘收起后全屏层恢复。
- 恢复过程只滚动 `#aiMsgs` 到最新消息，不改写页面缩放级别。

### 23.2 横向溢出防护

- `html`/`body` 限制最大宽度为 100%并隐藏横向溢出；对话层和对话主体设置 `min-width:0`。
- 助手气泡使用 `overflow-wrap:anywhere` 和 `word-break:break-word`，防止 URL、长数字或 LLM 连续文本撑宽对话层。
- 关闭对话层时必须先停止语音、移除输入焦点，再恢复背景滚动位置。

### 23.3 猫头“我的”入口

- `#userEntry` 使用内联 SVG 描边绘制带双耳的猫头轮廓，不引用 `avatar_data`、`mascot.png` 或其他位图。
- SVG 定位为按钮外形，按钮中心唯一可见文字节点为“我的”；不根据昵称或头像变更。
- 按钮宽高不小于 52px，SVG 使用 `currentColor` 和非缩放线宽，支持 hover/focus/active 状态；`aria-label="进入我的"` 保持不变。

### 23.4 测试

- [x] 静态测试锁定 16px 手机输入、`visualViewport`、发送后 `blur()`、横向溢出防护及无头像的猫头入口。
- [x] 375×812 浏览器模拟键盘高度变化，验证聚焦、发送、收键盘后无横向溢出。
- [x] 375×812 与 812×375 登录后猫头“我的”入口完整可见、可点击，“我的”页功能无回归。
- [x] `GET /health` 返回 v2.10.1；375×812 生产页输入字号 16px，键盘模拟高度 500px 时对话层等高，发送后焦点清除，恢复 812px 时 `scrollWidth=clientWidth=375`；登录入口文案仅为“我的”、位图数为 0。

---

## 24. v2.10.2 键盘防穿模与日期解析规格

### 24.1 全屏层层级与视口收敛

- `body.panel-open::after` 创建 `position:fixed; inset:0` 的同色遮罩，z-index 为 80；首页 `.mobile-ai-dock` 为 60，`.app-panel` 为 90。
- 遮罩无交互、无动画，只在 `.panel-open` 期间存在，用于覆盖微信 WebView 键盘动画中对话层与布局视口之间的瞬时缝隙。
- `restoreMobileViewport()` 先 `blur()`，立即按 `visualViewport` 同步，再于键盘动画后分阶段同步；若当前无可编辑元素聚焦且 `visualViewport.scale == 1`，最终高度取 `visualViewport.height` 与 `window.innerHeight` 的较大值并将顶部偏移归零。
- 不禁用手动缩放；当 `visualViewport.scale != 1` 时不强制完整屏幕高度。

### 24.2 规则日期解析器

`recognizer.extract_entities()` 的日期优先级：

```text
相对日期区间/语义角色
  → 中文月日区间
  → 数字日期区间
  → 日期 + 租期天数推算
```

- 相对日映射：今天=0、明天=1、后天=2、大后天=3，基准为服务器 `date.today()`。匹配顺序必须优先“大后天”以避免被“后天”截断。
- 两个日期按文本顺序映射为 `start_date`/`end_date`；单日期含“还/归还/还机/结束/到期/延期/改期”映射为 `end_date`，否则映射为 `start_date`。
- 数字 token 支持 `YYYY-M-D`、`YYYY/M/D`、`YYYY.M.D`、`M-D`、`M/D`、`M.D`；区间分隔符由两个 token 之间的文字决定，支持“到/至/~/-/—”。
- 未显式年份的 token 取最近未来日；若第二日早于第一日且第二 token 无年份，把第二日调整到次年。
- 租期天数支持阿拉伯数字与一至三十一的中文数字，`end_date = start_date + days - 1`。

### 24.3 导购等待租期转换

```text
waiting_dates + start_date + end_date  → inventory_checked
waiting_dates + start_date             → waiting_end_date
waiting_dates + end_date               → waiting_start_date
waiting_end_date + duration_days       → inventory_checked
```

- 日期实体优先于“发散问题”判断，不调用 LLM。
- 只得到一个边界时保留已识别值，并仅追问另一边界；不重置已选设备、场景和配置。
- 租期完整后继续真实库存、计价和免押选择，不绕过原有业务数据检查。

### 24.4 测试

- [x] 单元测试覆盖相对日期、语义角色、斜杠/点号/中文区间、中文天数、跨年与无效 token 忽略。
- [x] 导购集成测试覆盖“明天租，后天还”、分两轮补充起止日、已知起租日+天数和斜杠日期区间。
- [x] 静态页面测试锁定 60/80/90 层级、分阶段视口收敛和不禁用缩放。
- [x] 375×812 生产页在键盘模拟 500px 后恢复 812px，`scrollWidth=clientWidth=375`、输入焦点已清除；遮罩 z-index=80、首页按钮=60、AI 层=90。`GET /health` 返回 v2.10.2；生产 `/api/chat` 对“明天租，后天还”返回两天报价，对 `7/20~7/23` 返回四天报价并进入免押选择。

---

## 25. v2.10.3 库存候选确认与下单跳转规格

### 25.1 会话状态

会话新增 `checkout_candidate`：

```json
{
  "camera_id": "R10",
  "config_id": "配置主键",
  "config_name": "佳能R10",
  "start_date": "2026-07-19",
  "end_date": "2026-07-20",
  "quantity": 1
}
```

状态转换：

```text
idle + 唯一设备/完整租期/库存充足 -> checkout_candidate_ready
checkout_candidate_ready + 肯定答复 -> checkout_ready（保留同一候选并返回下单动作）
checkout_candidate_ready + 否定答复 -> idle（清除候选）
checkout_candidate_ready + 新设备或新租期 -> 重新查询并替换候选
checkout_ready + 点击 prefill_order -> checkout_form_filled（仅前端表单状态）
```

肯定/否定只做去空格、去句末标点后的整句匹配，避免把包含“可以”等词的发散问题误判为确认。候选随 `Conversation.entities.checkout_candidate` 持久化，`_restore_session()` 在进程内缓存丢失时恢复。

### 25.2 库存处理与动作契约

- `_handle_inventory_query()` 在匹配到配置、租期完整且请求数量库存充足时，选用查询结果对应的默认配置并返回 `checkout_candidate`。
- 配置不匹配、库存不足、日期缺失或请求数量大于可用量时不生成候选。
- `prefill_order` 动作统一使用标签“下单”，payload 为 `camera_id/config_id/start_date/end_date/quantity`，可选携带可靠的 `shipping_address`；不得调用订单创建接口。
- 简短肯定答复应在 FAQ、LLM 和通用意图识别之前处理；简短否定答复只在存在候选时生效。

### 25.3 持久化与前端

- 每轮结构化库存回答把候选写入当前 `IntentResult.entities`，进而保存到会话缓存和 `conversations.entities`。
- 后续肯定答复沿用候选生成 `prefill_order`；否定答复持久化空候选，防止跨实例恢复旧数据。
- 前端继续复用 `onAct('prefill_order')`：关闭 AI 层、选设备和配置、写日期与数量、查询报价、滚动到订单区域；地址缺失时由客户补填。
- 点击动作不预留库存、不创建 `orders`、不触发资金状态或飞书同步。

### 25.4 测试

- [x] 单元测试覆盖首次库存候选、肯定确认、否定清除、库存不足、数量不足、紧凑“明后天”和跨实例恢复；全量 149 项通过。
- [x] 前端静态与 375×812 浏览器测试覆盖动作标签、payload 预填顺序、设备/配置/日期/数量/报价/六项地址输入、跳转后无横向溢出与无自动下单。
- [x] `bozipaopao.cn` 健康检查返回 v2.10.3；生产无副作用对话验证“租佳能R10明后天 → 对”，第一轮和确认轮均返回 `prefill_order`，点击后下单页正确预填且控制台无错误。

---

## 26. v2.10.4 全阶段发散问答规格

### 26.1 状态转换

```text
collecting_dimensions / waiting_dates / checkout_ready
  + reasonable_side_question
  -> paused_for_side_question

paused_for_side_question + knowledge_hit -> paused_for_side_question（知识库原文）
paused_for_side_question + knowledge_miss -> paused_for_side_question（LLM短回答）
paused_for_side_question + continue_current -> previous_state
paused_for_side_question + restart_from_detour -> collecting_dimensions（清除旧候选）
```

- `sales_journey.paused=true` 表示旧导购草稿保留但当前不消费普通用户文本。
- `sales_journey.detour_message` 只保存脱敏后的最近发散问题，供“按新需求重新选设备”恢复语义；最长 500 字。
- `checkout_candidate` 在“继续当前下单”前保留；选择重新推荐时与旧 `sales_journey` 一并清除。
- 暂停状态禁止 `_relation_reply()` 把“对/是的”关联到旧候选。

### 26.2 发散识别

`is_side_question()` 从仅覆盖 `waiting_dates` 扩展到所有活动导购阶段，但下列输入仍交回原状态机：

- 当前缺失维度的直接答案（场景、经验或偏好）；
- 新日期、租期天数、明确免押选择、结构化收货信息；
- “继续填写租期 / 重新选择设备 / 继续当前下单 / 按新需求重新选设备”等控制动作；
- 明确的换机指令，如“换成R10”，与询问“R10适合新疆吗”区分。

问题词覆盖问号、吗、怎么、为什么、能不能、可以、推荐、区别、参数、镜头、拍照、旅行地点和拍摄风格；新增新疆、西藏、草原、沙漠、雪山等旅行场景词，但规则不依赖单一地点特例。

### 26.3 知识库与 LLM 契约

路由顺序保持：安全拦截 → 确定性业务能力 → FAQ 检索 → 发散 LLM → 普通意图。发散 LLM 调用增加只读 `business_context`，内容来自 `cameras/camera_configs` 的真实在售名称与公开定位，不包含库存结果、用户个人信息、订单、价格承诺或内部密钥。

`guide.generate_answer(message, history, side_question=True, business_context=...)`：

- 系统提示明确只回答当前新问题，不继续旧流程；
- 正文清洗后最多 180 字，前端统一展示“回答由AI生成”；
- 发散回答等待模型最多 25 秒；若模型先给有效建议、再追加“请咨询客服”，保留至少 30 字的实质回答并裁掉客服尾句，纯客服回复仍按客服口径处理；
- 模型不可用或失败时，合理选购/拍摄/操作问题返回本地安全引导，`answer_source=business_data`；不合理与危险请求仍由前置安全规则返回客服口径。

### 26.4 动作与副作用

- 完整设备和租期：`继续当前下单`、`按新需求重新选设备`；未完整租期：沿用 `继续填写租期`、`重新选择设备`。
- 动作继续使用 `guide_choice`，前端发送按钮标签；服务端从 `detour_message` 恢复新需求，不信任前端携带业务状态。
- 发散问答及两个恢复动作不写订单、占用、资金记录或飞书；仅写脱敏会话记录。

### 26.5 测试

- [x] 覆盖截图复现路径、FAQ优先、LLM标记与180字、客服尾句清洗、LLM失败安全降级、连续发散、恢复旧下单、按新问题重选及跨实例恢复；全量 157 项通过。
- [x] 375×812 本地浏览器验证安全降级、恢复/重选和新疆场景继承；生产浏览器验证 LLM 回答、按钮换行、对话滚动、`scrollWidth=clientWidth=375` 与无自动下单。
- [x] `bozipaopao.cn/health` 返回 v2.10.4；生产“租佳能A620明后天 → 想要去新疆拍照，推荐哪一款”第二轮为 `guided_sales_side_question`、`answer_source=llm`，展示 AI 标记与两个动作，控制台无错误。

---

## 27. v2.10.5 租客终态订单删除规格

### 27.1 状态与权限

```text
cancelled / completed + customer_delete -> 原状态不变，customer_deleted_at=UTC now
其他状态 + customer_delete -> 拒绝（order_not_deletable）
```

- 触发者必须是订单本人；商家后台列表不按 `customer_deleted_at` 过滤。
- `DELETE /api/orders/{id}/record?version=n` 使用乐观锁；已隐藏订单重复调用直接返回成功。
- 删除按钮仅渲染在 `cancelled/completed` 订单卡，并带订单号辅助标签与二次确认。

### 27.2 副作用与同步门

- 写入 `orders.customer_deleted_at`，递增 `orders.version`，记录 `order_changes.customer_delete`。
- 不删除 `orders/order_items/order_changes`、地址、陪伴事件或评价，不再次释放 occupancy。
- 不调用 `_sync_to_feishu`；飞书中已同步的业务订单继续保留，方便财务、物流、理赔与审计。
- C 端 `GET /api/orders` 统一过滤已隐藏订单，因此首页订单区与“我的”中心同步消失。

### 27.3 迁移与测试

- `ensure_runtime_schema()` 在既有 SQLite/PostgreSQL `orders` 表自动补 `customer_deleted_at`；不重复 seed，不清历史数据。
- 单元测试覆盖允许状态、非法状态、本人权限、列表过滤、审计保留和重复删除幂等；全量 161 项通过。
- 真实浏览器覆盖创建→取消→手机端删除→两个订单入口同步刷新；375px 视口无横向溢出，控制台无错误。
- `bozipaopao.cn/health` 返回 v2.10.5；生产测试订单删除后 `GET /api/orders` 不再返回该订单，按订单号读取仍确认原记录及 `cancelled` 状态保留。
