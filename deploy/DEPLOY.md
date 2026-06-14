# 生产部署手册（国内云服务器）— v2.2

把「猫猫头相机租赁」部署到国内云服务器，对外 24 小时提供服务。对应 PRD/Spec v2.2 §部署章节。

> ⚠️ 三件**只能你来做、且不可加速**的前置：① 买服务器（实名）② 买域名 ③ **ICP 备案**（管局审核约 2–3 周，国内服务器开放网站强制）。备案没下来之前，对外只能先用临时演示链接（Cloudflare Tunnel / ngrok）过渡。

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
