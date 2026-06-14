"""把本地 SQLite 数据迁移到 DATABASE_URL 指向的库 (v2.3, 用于迁到 Supabase/Postgres)。

用法:
    source .venv/bin/activate
    # 目标库由 DATABASE_URL 决定(运行时设为 Supabase 连接串)
    DATABASE_URL='postgresql+psycopg://USER:PWD@HOST:5432/postgres?sslmode=require' \
        python -m scripts.migrate_sqlite_to_pg --truncate

参数:
    --source PATH   源 SQLite 文件 (默认 ./rental.db)
    --truncate      迁移前先按外键反序清空目标库各表(便于重跑; 默认不清)

说明:
- 目标表结构由 ORM 自动创建(Base.metadata.create_all)。
- 按 Base.metadata.sorted_tables(外键安全顺序)逐表整表复制。
- 因为用的是带类型的 metadata, JSON/日期/布尔/Decimal 会被正确反序列化再写入目标库。
- 目标库**不能**也是这个源 SQLite(会自我覆盖); 脚本会拦截相同 URL。
"""
from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine

from app.config import settings
from app.models import Base  # noqa: F401  导入即注册所有表到 metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite -> DATABASE_URL 数据迁移")
    parser.add_argument("--source", default="rental.db", help="源 SQLite 文件路径")
    parser.add_argument("--truncate", action="store_true", help="迁移前清空目标各表")
    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"❌ 源文件不存在: {args.source}")
        return 1

    source_url = f"sqlite:///{args.source}"
    target_url = settings.database_url
    if target_url.startswith("sqlite") and args.source in target_url:
        print("❌ 目标库就是源 SQLite, 请把 DATABASE_URL 设为目标(如 Supabase)连接串。")
        return 1

    print(f"源:   {source_url}")
    print(f"目标: {target_url.split('@')[-1] if '@' in target_url else target_url}")

    src = create_engine(source_url)
    dst = create_engine(target_url)

    # 1) 目标库建表
    Base.metadata.create_all(dst)

    tables = list(Base.metadata.sorted_tables)  # 外键安全顺序(父表在前)

    # 2) 可选清空(反序: 子表先删)
    if args.truncate:
        with dst.begin() as conn:
            for table in reversed(tables):
                conn.execute(table.delete())
        print("已清空目标库各表。")

    # 3) 逐表复制
    total = 0
    with src.connect() as s, dst.begin() as d:
        for table in tables:
            rows = [dict(r._mapping) for r in s.execute(table.select())]
            if not rows:
                print(f"  {table.name}: 0")
                continue
            d.execute(table.insert(), rows)
            total += len(rows)
            print(f"  {table.name}: {len(rows)}")

    print(f"✅ 迁移完成, 共 {total} 行。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
