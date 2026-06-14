# 云平台部署（Railway / Render）— GitHub 推送即部署

适合"快速上线给人用、不想管服务器"。两个平台都跑**常驻容器**，所以本项目的 APScheduler 定时任务和 SQLite 都能正常工作（与 Vercel 不同）。仓库：https://github.com/lilili0611/AI-Rental-Assistant

> ⚠️ 这两个平台都在**海外**：免备案、上手快，但**国内访问速度一般**。如果主要面向国内长期用户，仍建议用 `deploy/DEPLOY.md` 的国内云服务器方案。

仓库已内置：`Procfile`（启动命令）、`runtime.txt`（Python 3.11）、`render.yaml`（Render 蓝图）、启动时按 `AUTO_SEED` 自动灌种子。

---

## 关键约束（两平台通用）

1. **单实例 / 1 worker**：APScheduler 在进程内跑（预留扫描、飞书轮询），**不要**开多实例/多 worker，否则定时任务重复执行。`Procfile` 已写死 `--workers 1`。
2. **SQLite 必须挂持久盘**：否则重部署/休眠后数据清零。下面每个平台说明里都配了卷。数据量大了再改 `DATABASE_URL` 迁 PostgreSQL（代码无需改）。
3. **必须设的环境变量**：
   - `ENCRYPTION_KEY`：强随机串（关系到密码哈希 + 登录令牌签名）。本地生成：`python3 -c "import secrets;print(secrets.token_urlsafe(48))"`
   - `DATABASE_URL`：指向持久盘里的 sqlite 文件（见下）
   - `AUTO_SEED=true`：首次部署自动灌入设备目录（库非空则跳过，不会覆盖）
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
5. 部署完成后，Settings → Networking → **Generate Domain**，得到公网网址。
6. 访问 `https://<域名>/health` 应返回 ok；`/` 前端、`/admin` 后台。

## 方式 B：Render（用本仓库的 render.yaml 蓝图）

1. 打开 https://render.com → 用 GitHub 登录。
2. **New + → Blueprint** → 选本仓库。Render 读取根目录 `render.yaml` 自动建服务：已配好启动命令、健康检查、`/var/data` 持久盘、`ENCRYPTION_KEY` 自动生成、`DATABASE_URL`、`AUTO_SEED=true`。
3. 点 **Apply** 部署（持久盘需 starter 付费套餐；免费套餐无盘会丢数据）。
4. 部署完成后访问 Render 给的 `onrender.com` 网址，`/health` 验证。

---

## 部署后必做

1. **改后台密码**（演示口令 `admin888` 必须换）。在平台的一次性命令/Shell 里执行：
   ```bash
   python -m scripts.set_staff_password 13900000002 <你的新密码>
   ```
   （Railway: 项目 → 该服务 → 可开 shell；Render: Shell 标签页。）
2. 商家后台登录：`https://<域名>/admin`，手机号 `13900000002` + 新密码。
3. 演示客户登录：前端用手机号 `13800000001`（或任意手机号自动注册为客户）。

## 常见问题

- **打开是空的/没有设备**：`AUTO_SEED` 没设或数据库非空。确认变量已设；首次部署看日志是否打印「灌入演示目录」。
- **订单刷新就没了**：没挂持久盘，或 `DATABASE_URL` 没指向卷目录。
- **后台登录一直失败**：`ENCRYPTION_KEY` 部署后又改过（令牌/密码哈希都依赖它）；重设密码并重新登录。
- **飞书没同步物流**：飞书表需手动加「快递公司」「物流单号」两列（见 Spec §7.4）。
