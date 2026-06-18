# 生产部署手册 — v2.2 / v2.3

两条上线路线，按需选：
- **方案 A：Railway + Supabase（海外，最快，推荐先用）** —— 见下方「方案 A」。GitHub 推送即部署，数据库用 Supabase 托管 Postgres，免备案、免买服务器、免装环境。
- **方案 B：国内云服务器 + 备案（面向国内大量用户的长期方案）** —— 见后面「方案 B」。访问快、可控，但需买服务器、ICP 备案（约 2–3 周）。

代码同一套，靠 `DATABASE_URL` 切换数据库；两条路线可随时互迁。

---

## 方案 A：Railway + Supabase（推荐，最快）

> 对应 PRD/Spec v2.3。Railway 在海外、无代理，连 Supabase 零障碍；**本机无需连 Supabase**（本机开发继续用 SQLite）。

### A0. 架构

```
用户浏览器 → (HTTPS) Railway(uvicorn, 单进程, $PORT) → Supabase 托管 Postgres
                              └ 进程内 APScheduler（预留扫描 / 飞书轮询）
```

- 数据库在 Supabase，**Railway 不需要挂 Volume**。
- 启动文件 `Procfile`：`web: uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1`（单进程，定时任务才不会重复跑）。

### A1. 准备 Supabase

1. https://supabase.com → 用 GitHub 登录 → **New project**（设并记住数据库密码，Region 选 Tokyo/Singapore）。
2. 顶部 **Connect** 按钮 → **Connection string → URI → Session pooler**，复制连接串，把 `[YOUR-PASSWORD]` 换成你的密码。
   - 形如 `postgresql://postgres.<ref>:<password>@aws-1-<region>.pooler.supabase.com:5432/postgres`
   - 结尾建议加 `?sslmode=require`。密码含特殊字符要 URL 编码（如 `@`→`%40`）。

### A2. 在 Railway 部署

1. https://railway.com → New Project → **Deploy from GitHub repo** → 选 `AI-Rental-Assistant`。
   - 若列表看不到仓库：去 https://github.com/settings/installations → Railway → Configure → 把该仓库加入授权。
2. 进入服务 → **Variables（环境变量）** 添加：

   | 变量 | 值 | 说明 |
   |------|----|----|
   | `DATABASE_URL` | 上一步的 Supabase 连接串 | 必填 |
   | `ENCRYPTION_KEY` | 强随机串（`python3 -c "import secrets;print(secrets.token_urlsafe(48))"`） | 必填，关系到密码哈希与令牌签名 |
   | `AUTO_SEED` | `true` | 首次启动自动建表+灌设备目录；灌完可改回 `false` |
   | `DEEPSEEK_API_KEY` | 你的 key | 可选，AI 对话用 |
   | `FEISHU_ENABLED` 等 | 见 `.env.production.example` | 可选，飞书同步 |

3. 保存后 Railway 自动构建并启动。首次启动会：连 Supabase → `create_all` 建表 → 因 `AUTO_SEED=true` 灌入演示目录。
4. 在 Settings → Networking **生成域名**（Generate Domain）拿到 `https://xxx.up.railway.app`。

### A3. 验证

- `https://xxx.up.railway.app/` 能看到设备列表 = Supabase 通了。
- Supabase 控制台 **Table Editor** 能看到 `cameras` / `orders` 等表与数据。
- `/admin` 用演示员工 `13900000002` / `admin888` 登录。
- Railway 部署日志出现「AUTO_SEED: 数据库为空, 灌入演示目录…」。

### A4. 上线后必做

- [ ] Supabase 重置数据库密码、DeepSeek 重置 key（之前在对话/本地出现过），并更新 Railway 变量。
- [ ] 用 `scripts/set_staff_password.py` 改掉 `admin888`（在 Railway 的 Shell 里跑，或本机连 Supabase 跑）。
- [ ] 数据灌好后把 `AUTO_SEED` 改回 `false`。

### A5. 本地把数据迁到 Supabase（可选）

本机因代理（Shadowrocket TUN/fake-IP）无法直连 Supabase。若一定要从本机迁本地数据：在 Shadowrocket 加 `DOMAIN-SUFFIX,supabase.com,DIRECT` 直连规则后，
`DATABASE_URL='<supabase串>' python -m scripts.migrate_sqlite_to_pg --truncate`。
否则推荐直接用云端 `AUTO_SEED` 灌干净目录，再手动下几单测试。

---

## 方案 B：国内云服务器 + 备案

把「猫猫头相机租赁」部署到国内云服务器，对外 24 小时提供服务。对应 PRD/Spec v2.2 §部署章节。

> ⚠️ 三件**只能你来做、且不可加速**的前置：① 买服务器（实名）② 买域名 ③ **ICP 备案**（管局审核约 2–3 周，国内服务器开放网站强制）。备案没下来之前，对外只能先用临时演示链接（Cloudflare Tunnel / ngrok）过渡。

> 数据库同样推荐用 Supabase（把下文 SQLite 的 `DATABASE_URL` 换成 Supabase 连接串即可）；或用本机持久目录的 SQLite。

---

## 0. 架构一句话

```
用户浏览器 → (HTTPS) Nginx :443 → uvicorn 127.0.0.1:8000 (FastAPI 单进程) → SQLite 文件
                                         └ 进程内 APScheduler（预留扫描 / 飞书轮询）
```

- 单进程/单 worker（**重要**：APScheduler 在进程内，多 worker 会重复跑定时任务）。
- 数据库起步用 SQLite 文件（放持久目录、定期备份）；量级上来改 `DATABASE_URL` 迁 PostgreSQL。

---

## 1. 买服务器（你做）

- 阿里云 / 腾讯云「**轻量应用服务器**」，2核2G 起步够用（约 ¥24–60/月）。
- 系统选 **Ubuntu 22.04** 或 Debian 12。
- 安全组/防火墙：只放行 **80、443、22**；**不要**对公网开放 8000。

## 2. 域名 + 备案（你做，2–3 周）

1. 在同一家云厂商买域名，提交 **ICP 备案**（用这台服务器），等管局通过。
2. 备案通过后，把域名 A 记录解析到服务器公网 IP。

## 3. 装环境（服务器上）

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip nginx git
sudo mkdir -p /opt/rental /var/lib/rental /etc/rental
# 把代码放到 /opt/rental（git clone 或 scp 上传），然后：
cd /opt/rental
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. 配置环境变量

```bash
sudo cp deploy/.env.production.example /etc/rental/.env
sudo nano /etc/rental/.env      # 填真实值
# 生成强随机 ENCRYPTION_KEY：
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

`ENCRYPTION_KEY` 关系到**后台密码哈希与登录令牌签名**，务必强随机且保密。

## 5. 初始化数据库 + 设置后台密码

```bash
cd /opt/rental && source .venv/bin/activate
python -m scripts.seed_data                          # 首次：建表 + 演示数据
# 🔴 上线前必须改掉演示弱口令：
python -m scripts.set_staff_password 13900000002     # 交互式输入新密码
```

> 已有数据需保留时不要重复 seed（会清表）。新增字段的迁移：本项目历史用 `ALTER TABLE` 增列，迁移脚本随版本提供。

## 6. 进程守护（systemd）

```bash
sudo cp deploy/rental.service /etc/systemd/system/rental.service
sudo nano /etc/systemd/system/rental.service    # 核对 User/路径/EnvironmentFile
sudo systemctl daemon-reload
sudo systemctl enable --now rental
sudo systemctl status rental
curl -s http://127.0.0.1:8000/health             # 期望 {"status":"ok",...}
```

## 7. Nginx + HTTPS

```bash
sudo cp deploy/nginx.conf.example /etc/nginx/conf.d/rental.conf
sudo nano /etc/nginx/conf.d/rental.conf          # 改 your-domain.com
sudo nginx -t && sudo systemctl reload nginx
# 证书（acme.sh 示例）：
curl https://get.acme.sh | sh
~/.acme.sh/acme.sh --issue -d your-domain.com --nginx
# 签发后按 nginx.conf.example 里的 443 段启用 HTTPS，并把 80 跳转 443
```

## 8. 验证上线

- `https://your-domain.com/`        租客前端
- `https://your-domain.com/admin`   商家后台（账号 + 密码登录）
- `https://your-domain.com/health`  健康检查

---

## 9. 上线检查清单（务必逐条过）

- [ ] `ENCRYPTION_KEY` 已设为强随机，且未进 Git
- [ ] 已用 `set_staff_password.py` 改掉所有演示弱口令
- [ ] 防火墙只放行 80/443/22，8000 未暴露公网
- [ ] HTTPS 生效，HTTP 跳转 HTTPS
- [ ] `/health` 正常；`systemctl status rental` 为 active
- [ ] SQLite 文件在持久目录，已配置定期备份
- [ ] 飞书如启用：表中已有「快递公司/物流单号」列；凭证走环境变量

## 10. 日常运维

```bash
sudo journalctl -u rental -f          # 看日志
sudo systemctl restart rental         # 重启
cp /var/lib/rental/rental.db ~/backup/rental-$(date +%F).db   # 备份数据库
```

## 11. 更新发布

```bash
cd /opt/rental && git pull            # 或重新上传代码
source .venv/bin/activate && pip install -r requirements.txt
# 如有数据库结构变更，先执行对应迁移
sudo systemctl restart rental
```
