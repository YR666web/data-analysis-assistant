"""检查或显式执行药品分类迁移；管理员密码仅在终端临时输入。"""
from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

import mysql.connector
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "sql" / "001_add_drug_class.sql"
VALID_CLASSES = {"抗生素", "非抗生素"}


def inspect_schema(conn):
    """只执行 SELECT；区分待迁移、待分类和分类完成。"""
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'drugs'"
        )
        if not cursor.fetchone()[0]:
            raise ValueError("目标数据库没有 drugs 表，请核对数据库名称；本工具不创建演示数据库。")
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'drugs' "
            "AND column_name = 'drug_class'"
        )
        if not cursor.fetchone()[0]:
            return {"has_column": False, "counts": {}, "unclassified": None}
        cursor.execute("SELECT drug_class, COUNT(*) FROM drugs GROUP BY drug_class")
        counts = dict(cursor.fetchall())
        return {
            "has_column": True,
            "counts": counts,
            "unclassified": sum(n for label, n in counts.items() if label not in VALID_CLASSES),
        }
    finally:
        cursor.close()


def apply_migration(conn, sql_path=MIGRATION):
    """执行唯一的版本化 SQL 文件，消费全部结果后再提交数据回填。"""
    cursor = conn.cursor()
    try:
        cursor.execute(sql_path.read_text(encoding="utf-8"))
        # Connector/Python >= 9.7 supports multiple statements. Errors from later
        # statements can surface in nextset(), so success must wait for all sets.
        while True:
            if cursor.with_rows:
                cursor.fetchall()
            if not cursor.nextset():
                break
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def print_status(status):
    if not status["has_column"]:
        print("待升级：缺少 drugs.drug_class，当前查询仍按旧治疗领域推断。")
        return 2
    counts = status["counts"]
    print(f"明确分类：抗生素 {counts.get('抗生素', 0)} 条，非抗生素 {counts.get('非抗生素', 0)} 条。")
    if status["unclassified"]:
        print(f"待核对分类：{status['unclassified']} 条（NULL、空值或其他类别）；不会将其自动归为非抗生素。")
        return 2
    print("检查通过：分类字段存在，现有记录均已明确分类。")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只读检查（默认），使用应用配置")
    mode.add_argument("--apply", action="store_true", help="执行迁移，必须另行指定有权限的账号")
    parser.add_argument("--user", help="临时数据库账号；密码由终端提示输入，不写入 .env")
    parser.add_argument("--host", help="默认使用 .env 中的 MYSQL_HOST")
    parser.add_argument("--port", type=int, help="默认使用 .env 中的 MYSQL_PORT")
    parser.add_argument("--database", help="默认使用 .env 中的 MYSQL_DATABASE")
    args = parser.parse_args(argv)
    if args.apply and not args.user:
        parser.error("--apply 必须提供 --user，不能隐式使用应用的只读账号执行升级")

    config = {**dotenv_values(ROOT / ".env"), **os.environ}
    conn = None
    try:
        options = {
            "host": args.host or config.get("MYSQL_HOST", "localhost"),
            "port": args.port or int(config.get("MYSQL_PORT", "3306")),
            "database": args.database or config.get("MYSQL_DATABASE", "pharma_db"),
            "user": args.user or config.get("MYSQL_USER", "app_reader"),
            "charset": config.get("MYSQL_CHARSET", "utf8mb4"),
            "connection_timeout": 5,
            "use_pure": True,
            "autocommit": not args.apply,
        }
        print(f"目标：{options['host']}:{options['port']}/{options['database']}，账号：{options['user']}")
        options["password"] = (
            getpass.getpass("临时账号密码（不显示、不保存）：")
            if args.user else config.get("MYSQL_PASSWORD", "")
        )
        conn = mysql.connector.connect(**options)
        status = inspect_schema(conn)
        if args.apply:
            print("执行 001_add_drug_class.sql：新增分类字段，只补充内置示例药品的空分类。")
            print("MySQL DDL 自动提交；若回填失败，字段可能已创建，修复权限后可安全重跑。")
            apply_migration(conn)
            status = inspect_schema(conn)
            print("迁移执行完成。应用会在下次查询时自动使用新字段。")
        return print_status(status)
    except mysql.connector.Error as exc:
        if exc.errno in (1044, 1045, 1142, 1143, 1227):
            print(f"数据库拒绝访问或操作（错误 {exc.errno}）。升级账号需对目标 drugs 表具备 SELECT、ALTER、UPDATE 权限。")
            print("请由数据库管理员执行迁移，不要提升应用只读账号的权限。")
        else:
            print(f"数据库操作失败（错误 {exc.errno}）：{exc.msg}")
        return 1
    except (OSError, ValueError, EOFError) as exc:
        print(f"检查/迁移失败：{exc}")
        return 1
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
