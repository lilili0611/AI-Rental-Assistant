# 相机租赁 AI 助手系统 — 技术规格文档 (Spec)

| 项目 | 内容 |
|------|------|
| 文档类型 | Technical Specification |
| 版本 | v1.0 |
| 状态 | 评审稿 |
| 配套文档 | 《产品需求文档 (PRD)》 |
| 范围 | Phase 1–2 详细规格 + Phase 3–4 接口预留 |

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
| phone | VARCHAR(20) | UNIQUE, NOT NULL, INDEX | 手机号,登录标识 |
| name | VARCHAR(100) | | 姓名 |
| is_authenticated | BOOLEAN | DEFAULT false | 是否完成实名认证 |
| id_number_encrypted | VARCHAR(255) | NULL | 身份证号(AES-256 加密) |
| address_encrypted | VARCHAR(255) | NULL | 地址(加密) |
| role | VARCHAR(20) | DEFAULT 'customer' | customer/sales/warehouse/finance/admin |
| credit_score | INTEGER | DEFAULT 100 | 信用分 |

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
| daily_price | NUMERIC(10,2) | NOT NULL | 该配置日租金 |
| deposit_amount | NUMERIC(10,2) | NOT NULL | 该配置押金 |
| accessories | JSONB | DEFAULT '[]' | 配件列表 |

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
| deposit_amount | NUMERIC(10,2) | | 押金 |
| discount_amount | NUMERIC(10,2) | DEFAULT 0 | 优惠抵扣 |
| total_price | NUMERIC(10,2) | | 应付总额 |
| paid_amount | NUMERIC(10,2) | DEFAULT 0 | 已收金额(人工录入) |
| payment_note | VARCHAR(500) | NULL | 🔴 支付凭证备注(人工填) |
| rental_start | DATE | NOT NULL | 租期起 |
| rental_end | DATE | NOT NULL | 租期止 |
| created_by | UUID | | 创建者 |
| version | INTEGER | DEFAULT 1 | 乐观锁版本号 |
| source | VARCHAR(20) | DEFAULT 'ai' | ai/feishu/manual |
| last_modified_by | UUID | | 最后修改者 |

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
                  (48h未付/取消)                  B端审核
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
| shipped | 已发货 | active | 仓库 |
| active | 使用中 | returned | 客户签收触发 |
| returned | 已归还待验收 | completed | 仓库 |
| completed | 已完成 | — | 系统(对账后) |
| cancelled | 已取消 | — | 多角色 |

> 🔴 **关键修正**:`pending_payment → paid` 的转换由**人工确认收款**触发,不是支付回调。`paid` 状态记录 `paid_amount` 和 `payment_note`。

**取消规则的状态约束:**
- `pending_payment` 阶段取消:免费(若在 48h 内),释放占用
- `paid`/`confirmed` 阶段取消:扣 10% 手续费,退余额
- `shipped` 及之后:不可直接取消

### 3.2 预留状态机

```
active ──转为订单──> confirmed
   │
   └──30分钟超时──> expired (释放占用)
   │
   └──用户取消──> cancelled (释放占用)
```

后台 Celery 定时任务每分钟扫描 `expires_at < now()` 且 `status='active'` 的预留,置为 expired 并释放对应 occupancy。

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
  "total_due": 2810.00
}
```

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
  "delivery_address_id": "uuid",
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

查询当前用户订单列表。支持 status、page、limit 筛选。

### 4.6 飞书同步 (Phase 2,内部接口)

不对外暴露 HTTP,由 Service + Celery 实现。详见第 7 章。

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

```
days = (end_date - start_date).days   # 含起不含止,或按业务定义
subtotal = daily_price × days

# 天数折扣
day_discount = match days:
    1..3   -> 1.0
    4..7   -> 0.85
    8..30  -> 0.70
    31+    -> 0.60

# 季节折扣(查配置表,按起始日所在月)
seasonal_discount = seasonal_config.get(start_date.month, 1.0)

# 叠加相乘
after_discount = subtotal × day_discount × seasonal_discount
final_price = after_discount - coupon_discount
total_due = final_price + deposit
```

> ⚠️ "天数"的算法(含端点与否)需确认:租 9/1–9/3 算 2 天还是 3 天?建议按"日历天数 + 1"即 3 天,符合租赁直觉,但需业务确认。

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
- < 0.6:转人工

**涉及金钱的操作(下单/改单/取消)即使高置信度也需二次确认。**

### 6.3 权限校验

每个意图标注 `requires_auth`。order_* 系列需认证 + 仅操作本人订单。校验在 API 层用 FastAPI 依赖注入实现。

---

## 7. 飞书双向同步 (Phase 2)

### 7.1 同步方向

**AI → 飞书(事件驱动):** 订单创建/状态变更时,Service 层触发写入飞书多维表格对应行。失败重试 3 次(指数退避),仍失败则告警并标记 `sync_pending`。

**飞书 → AI(轮询 + Webhook):** Celery 每 30 秒轮询飞书最近变更;同时接收飞书 Webhook 推送(优先)。变更回流后更新本地订单。

### 7.2 字段映射

| 本地字段 | 飞书列 |
|---------|--------|
| id | 订单号 |
| status | 订单状态 |
| rental_start/end | 租期 |
| total_price | 应付金额 |
| paid_amount | 已收金额 |
| ... | ... |

### 7.3 冲突解决

两侧同时改 → 比较 `last_modified_at` 时间戳,**后改的胜出**。检测到冲突写审计日志并告警。乐观锁 `version` 防止并发覆盖。

---

## 8. Phase 3–4 接口预留

以下仅预留接口轮廓,详细规格待对应 Phase 启动前补充(依赖 PRD 待确认项)。

| 模块 | 预留接口 | 依赖 |
|------|---------|------|
| RAG 问答 | POST /api/chat 内部增强检索 | ⚠️ 需语料 |
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
