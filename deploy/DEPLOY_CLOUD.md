# 云平台部署（Railway / Render / Vercel）— GitHub 推送即部署

适合"快速上线给人用、不想管服务器"。Railway / Render 跑**常驻容器**，SQLite 挂持久盘即可。Vercel 跑 **Serverless Function**，必须外接 Postgres/Supabase/Neon 等数据库，并用 Vercel Cron 触发自动任务。仓库：https://github.com/lilili0611/AI-Rental-Assistant

> ⚠️ 这两个平台都在**海外**：免备案、上手快，但**国内访问速度一般**。如果主要面向国内长期用户，仍建议用 `deploy/DEPLOY.md` 的国内云服务器方案。

仓库已内置：`Procfile`（启动命令）、`runtime.txt`（Python 3.11）、`render.yaml`（Render 蓝图）、启动时按 `AUTO_SEED` 自动灌种子。

---

## 关键约束

1. **Railway / Render：单实例 / 1 worker**。APScheduler 在进程内跑（预留扫描、飞书轮询），**不要**开多实例/多 worker，否则定时任务重复执行。`Procfile` 已写死 `--workers 1`。
2. **Railway / Render：SQLite 必须挂持久盘**。否则重部署/休眠后数据清零。下面每个平台说明里都配了卷。数据量大了再改 `DATABASE_URL` 迁 PostgreSQL（代码无需改）。
3. **Vercel：不要用 SQLite 文件做生产库**。Vercel Function 文件系统不可作为持久数据库，必须配置外部 Postgres 连接串。
4. **Vercel：自动取消、飞书补偿同步和陪伴提醒走 `/api/cron/sweep`**。Hobby 计划只使用每天一次的 Vercel Cron；用户打开订单陪伴页时会即时补齐应有提醒。若要严格按小时主动触达，需要升级 Pro、使用外部定时器，或改用 Railway/Render/服务器。
5. **必须设的环境变量**：
   - `ENCRYPTION_KEY`：强随机串（关系到密码哈希 + 登录令牌签名）。本地生成：`python3 -c "import secrets;print(secrets.token_urlsafe(48))"`
   - `DATABASE_URL`：Railway / Render 可指向持久盘 SQLite；Vercel 必须指向 Postgres/Supabase/Neon
   - `AUTO_SEED=true`：首次部署自动灌入设备目录（库非空则跳过，不会覆盖）
   - `CRON_SECRET`：Vercel Cron 访问 `/api/cron/sweep` 的密钥；本地生成：`python3 -c "import secrets;print(secrets.token_urlsafe(32))"`
   - 飞书如需：`FEISHU_ENABLED=true` + `FEISHU_APP_ID/SECRET/BITABLE_APP_TOKEN/ORDER_TABLE_ID`

---

## 方式 A：Railway（推荐，卷配置最简单）

1. 打开 https://railway.app → 用 GitHub 登录。
2. **New Project → Deploy from GitHub repo** → 选 `AI-Rental-Assistant`。Railway 自动识别 Python + `Procfile`。
3. 加持久卷：项目里 **New → Volume**，Mount path 填 `/var/data`。
4. **Variables** 里加：
   - `ENCRYPTION_KEY` = （你生成的强随机串）
   - `DATABASE_URL` = `sqlite:////var/data/rental.db`  ← 注意是 4 个斜杠（绝对路径）
   - `AUTO_SEED` = `true`
5. 部署完成后，Settings → Networking → **Generate Domain**，得到临时公网网址。
6. 在 Networking 里继续添加 Custom Domain：`bozipaopao.cn` 和 `admin.bozipaopao.cn` 都绑定到同一个 Railway 服务；DNS 按 Railway 页面给出的目标值配置。
7. 访问 `https://bozipaopao.cn/health` 应返回 ok；`https://bozipaopao.cn/` 是客户前端，`https://admin.bozipaopao.cn/` 是商家后台。

## 方式 B：Render（用本仓库的 render.yaml 蓝图）

1. 打开 https://render.com → 用 GitHub 登录。
2. **New + → Blueprint** → 选本仓库。Render 读取根目录 `render.yaml` 自动建服务：已配好启动命令、健康检查、`/var/data` 持久盘、`ENCRYPTION_KEY` 自动生成、`DATABASE_URL`、`AUTO_SEED=true`。
3. 点 **Apply** 部署（持久盘需 starter 付费套餐；免费套餐无盘会丢数据）。
4. 部署完成后访问 Render 给的 `onrender.com` 网址，`/health` 验证。
5. 在 Render 的 Custom Domains 里添加 `bozipaopao.cn` 和 `admin.bozipaopao.cn`；DNS 按 Render 页面给出的记录配置。两个域名指向同一个服务，代码会自动区分客户前端和商家后台。

## 方式 C：Vercel（需外部数据库）

1. 打开 https://vercel.com/ → 用 GitHub 登录。
2. New Project → Import Git Repository → 选 `AI-Rental-Assistant`。
3. Environment Variables 里至少添加：
   - `DATABASE_URL` = 外部 Postgres/Supabase/Neon 连接串，必须带 SSL（例如 `?sslmode=require`）
   - `ENCRYPTION_KEY` = 强随机串
   - `AUTO_SEED` = `true`（首次部署用；灌好后可改为 `false`）
   - `SESSION_COOKIE_SECURE` = `true`
   - `ENABLE_PHONE_LOGIN` = `false`
   - `CRON_SECRET` = 强随机串
   - 飞书如需：`FEISHU_ENABLED=true` + `FEISHU_APP_ID/SECRET/BITABLE_APP_TOKEN/ORDER_TABLE_ID`
4. 部署后访问 Vercel 临时域名的 `/health` 验证。
5. Project Settings → Domains 添加 `bozipaopao.cn` 和 `admin.bozipaopao.cn`。
6. 到域名服务商处配置 DNS：根域名通常指向 Vercel 的 A 记录 `76.76.21.21`，`admin` 子域名通常配置 CNAME 到 Vercel 提示的目标；以 Vercel Domains 页面提示为准。
7. 验证 `/api/chat` 可连续完成导购反问；登录后验证订单“陪伴服务”。未配置物流提供器时，位置和预计送达必须为空并显示降级说明。
8. v2.10.5 起服务启动会为既有 `orders` 表自动补 `customer_deleted_at`；部署后验证已取消/已完结订单可从租客列表删除、商家后台记录仍保留。不要重新 seed 生产库。

## 正式域名规划

- 客户前端：`https://bozipaopao.cn/`
- 商家后台：`https://admin.bozipaopao.cn/`
- 可选：www 入口 `https://www.bozipaopao.cn/` 可解析到同一服务，作为客户前端入口。
- 云平台会给出具体 DNS 记录。通常 `admin` 子域名使用 CNAME；根域名 `@` 可能需要 ALIAS/ANAME/CNAME Flattening，或平台指定的 A 记录，按平台页面为准。

---

## 部署后必做

1. **改后台密码**（演示口令 `admin888` 必须换）。在平台的一次性命令/Shell 里执行：
   ```bash
   python -m scripts.set_staff_password 13900000002 <你的新密码>
   ```
   （Railway: 项目 → 该服务 → 可开 shell；Render: Shell 标签页。）
2. 商家后台登录：`https://admin.bozipaopao.cn/`，手机号 `13900000002` + 新密码。
3. 演示客户登录：前端用手机号 `13800000001`（或任意手机号自动注册为客户）。

## 常见问题

- **打开是空的/没有设备**：`AUTO_SEED` 没设或数据库非空。确认变量已设；首次部署看日志是否打印「灌入演示目录」。
- **订单刷新就没了**：没挂持久盘，或 `DATABASE_URL` 没指向卷目录。
- **后台登录一直失败**：`ENCRYPTION_KEY` 部署后又改过（令牌/密码哈希都依赖它）；重设密码并重新登录。
- **飞书没同步物流**：飞书表需手动加「快递公司」「物流单号」两列（见 Spec §7.4）。
