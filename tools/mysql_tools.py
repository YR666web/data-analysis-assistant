"""数据库三工具（TDD §7.2）。

- 连接配置从环境变量读取（TDD §12）：charset=utf8mb4，autocommit=True；
- 异常统一返回「连接数据库失败：{错误}」。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

# 加载项目根目录的 .env（保证直接运行本脚本也能读到数据库配置）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# 写操作关键字拦截（TDD §14，仅兜底；主防线是只读账号 + 参数化查询）
_FORBIDDEN_WRITE_PATTERN = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|TRUNCATE|ALTER|CREATE|RENAME|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

# 表名白名单：仅允许字母/数字/下划线，防 SQL 注入（TDD §14）
_TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


def _get_connection() -> mysql.connector.MySQLConnection:
    """按 TDD §12 建立数据库连接：utf8mb4 + autocommit。

    use_pure=True 走纯 Python 实现，规避 C 扩展在 asyncio 事件循环里的崩溃。
    """
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "pharma_db"),
        charset=os.getenv("MYSQL_CHARSET", "utf8mb4"),
        autocommit=True,
        use_pure=True,
    )


def list_sql_tables() -> str:
    """列出数据库所有表：有表返回「可用的表：a,b,c」，无表返回「没有可用的表」。"""
    try:
        conn = _get_connection()
    except Exception as e:  # noqa: BLE001
        return f"连接数据库失败：{e}"
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
        return "没有可用的表" if not tables else "可用的表：" + ",".join(tables)
    except Exception as e:  # noqa: BLE001
        return f"连接数据库失败：{e}"
    finally:
        conn.close()


def list_drugs_by_antibiotic_status(*, antibiotics: bool = True) -> str:
    """按明确药品类别列出抗生素或非抗生素药品（只读快速查询）。"""
    label = "抗生素" if antibiotics else "非抗生素"
    try:
        conn = _get_connection()
    except Exception as e:  # noqa: BLE001
        return f"连接数据库失败：{e}"
    try:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """SELECT generic_name, brand_name, specifications, dosage_form
                   FROM drugs WHERE drug_class = %s ORDER BY generic_name""",
                (label,),
            )
            rows = cursor.fetchall()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "errno", None) != 1054:
                raise
            # 兼容尚未迁移的只读数据库；明确标记为旧字段推断，不将其伪装成权威分类。
            legacy_condition = (
                "therapeutic_area = %s"
                if antibiotics
                else "therapeutic_area IS NOT NULL AND therapeutic_area <> %s"
            )
            cursor.execute(
                f"""SELECT generic_name, brand_name, specifications, dosage_form
                    FROM drugs WHERE {legacy_condition} ORDER BY generic_name""",
                ("抗生素",),
            )
            rows = cursor.fetchall()
            lines = _format_drug_rows(rows, label)
            lines.append(
                "注：当前数据库尚未升级，旧版结果按治疗领域字段推断；执行 sql/001_add_drug_class.sql 后可按明确类别查询。"
            )
            return "\n".join(lines)

        cursor.execute(
            "SELECT COUNT(*) AS count FROM drugs "
            "WHERE drug_class IS NULL OR drug_class NOT IN (%s, %s)",
            ("抗生素", "非抗生素"),
        )
        count_row = cursor.fetchone() or {}
        unclassified_count = count_row.get("count", 0) if isinstance(count_row, dict) else count_row[0]
        if not rows:
            lines = [f"数据库中没有明确标记为‘{label}’的药品。"]
            if unclassified_count:
                lines.append(f"另有 {unclassified_count} 条药品尚未完成类别标注，因此未纳入结果。")
            return "\n".join(lines)
        lines = _format_drug_rows(rows, label)
        lines.append(f"\n数据来源：pharma_db.drugs，按 drug_class = ‘{label}’ 筛选。")
        if unclassified_count:
            lines.append(f"另有 {unclassified_count} 条药品尚未完成类别标注，未纳入结果。")
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        if getattr(e, "errno", None) == 1054:
            return "药品分类字段尚未升级。请先执行 sql/001_add_drug_class.sql。"
        return f"查询药品表失败：{e}"
    finally:
        conn.close()


def _format_drug_rows(rows: list[dict], label: str) -> list[str]:
    if not rows:
        return [f"数据库中没有标记为‘{label}’的药品。"]
    lines = [f"数据库中共有 {len(rows)} 种标记为‘{label}’的药品："]
    for row in rows:
        details = [row.get("brand_name"), row.get("specifications"), row.get("dosage_form")]
        detail_text = "；".join(str(value) for value in details if value)
        lines.append(f"- **{row['generic_name']}**" + (f"（{detail_text}）" if detail_text else ""))
    return lines


def get_table_data(table_name: str) -> str:
    """读取指定表前 100 行：首行字段名，后续每行一条记录（逗号分隔）。"""
    if not _TABLE_NAME_PATTERN.match(table_name):
        return f"非法的表名：{table_name}"
    try:
        conn = _get_connection()
    except Exception as e:  # noqa: BLE001
        return f"连接数据库失败：{e}"
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM `{table_name}` LIMIT 100")
        rows = cursor.fetchall()
        if not rows:
            return f"查询表{table_name},结果没有数据"
        col_names = [desc[0] for desc in cursor.description]
        lines = [",".join(str(c) for c in col_names)]
        for row in rows:
            lines.append(",".join(str(v) for v in row))
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"连接数据库失败：{e}"
    finally:
        conn.close()


def execute_sql_query(sql: str) -> str:
    """执行自定义 SQL：返回同 get_table_data；无数据返回「执行语句{...},结果没有数据」。"""
    # 写操作关键字拦截（TDD §14 兜底，禁 DROP/DELETE/UPDATE 等）
    matched = _FORBIDDEN_WRITE_PATTERN.search(sql)
    if matched:
        return f"禁止执行写操作语句（含 {matched.group(1)}）"
    try:
        conn = _get_connection()
    except Exception as e:  # noqa: BLE001
        return f"连接数据库失败：{e}"
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        if not rows:
            return f"执行语句{sql},结果没有数据"
        col_names = [desc[0] for desc in cursor.description]
        lines = [",".join(str(c) for c in col_names)]
        for row in rows:
            lines.append(",".join(str(v) for v in row))
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        return f"连接数据库失败：{e}"
    finally:
        conn.close()


if __name__ == "__main__":
    print("=== list_sql_tables ===")
    print(list_sql_tables())
    print("\n=== get_table_data('drugs') ===")
    print(get_table_data("drugs"))
    print("\n=== execute_sql_query('SELECT COUNT(*) AS cnt FROM drugs') ===")
    print(execute_sql_query("SELECT COUNT(*) AS cnt FROM drugs"))
