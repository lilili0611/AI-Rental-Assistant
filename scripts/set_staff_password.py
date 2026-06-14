"""设置/重置员工后台登录密码 (v2.2)。

用法:
    source .venv/bin/activate
    python -m scripts.set_staff_password <手机号> [密码]

- 手机号必须是已存在的用户; 角色非员工时会提示但仍可设置(便于把某人提为员工另行处理)。
- 不传密码则进入交互式隐藏输入(推荐, 避免密码留在 shell 历史)。
- 密码以 PBKDF2 加盐哈希存储, 不存明文。
"""
from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app.core import security
from app.database import SessionLocal
from app.models.user import User


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("用法: python -m scripts.set_staff_password <手机号> [密码]")
        return 2
    phone = argv[1]
    password = argv[2] if len(argv) > 2 else None

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.phone == phone)).scalars().first()
        if not user:
            print(f"❌ 未找到手机号为 {phone} 的用户。请先让该用户登录一次或在数据库创建。")
            return 1
        if user.role == "customer":
            print(f"⚠️ 用户 {phone} 当前角色是 customer，不是员工，登录后台会被拒。"
                  f"如需作为员工，请先把其 role 改为 staff/admin。")

        if not password:
            password = getpass.getpass("请输入新密码: ")
            confirm = getpass.getpass("再次确认密码: ")
            if password != confirm:
                print("❌ 两次输入不一致。")
                return 1
        if len(password) < 6:
            print("❌ 密码至少 6 位。")
            return 1

        user.password_hash = security.hash_password(password)
        db.commit()
        print(f"✅ 已为 {user.name or phone}（{user.role}）设置后台密码。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
