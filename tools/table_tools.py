"""Session-scoped, deterministic spreadsheet inspection and aggregation."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from langchain_core.tools import tool

from api import context

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ROWS = 200_000
TABLE_EXTENSIONS = {".xlsx", ".xls", ".csv", ".tsv"}


def session_file(filename: str) -> Path:
    directory = context.get_session_dir()
    if not directory:
        raise ValueError("未设置会话目录")
    relative = Path(filename)
    if not filename or relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("文件名必须是当前会话内的相对路径")
    root = Path(directory).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ValueError("文件不存在或不属于当前会话")
    if target.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("文件超过 25 MB，请拆分后上传")
    return target


def _frame(path: Path, sheet: str | None = None) -> pd.DataFrame:
    if path.suffix.lower() in {".csv", ".tsv"}:
        if sheet not in (None, "data"):
            raise ValueError("CSV/TSV 的工作表名为 data")
        kwargs = dict(sep="\t" if path.suffix.lower() == ".tsv" else ",",
                      header=None, dtype=object, keep_default_na=False, nrows=MAX_ROWS + 2)
        try:
            raw = pd.read_csv(path, encoding="utf-8-sig", **kwargs)
        except UnicodeDecodeError:
            raw = pd.read_csv(path, encoding="gb18030", **kwargs)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        with pd.ExcelFile(path) as book:
            if sheet is None and len(book.sheet_names) != 1:
                raise ValueError("存在多个工作表，请先 inspect_table 并指定 sheet")
            selected = sheet or book.sheet_names[0]
            if selected not in book.sheet_names:
                raise ValueError(f"工作表不存在：{selected}")
            raw = pd.read_excel(book, sheet_name=selected, header=None, dtype=object,
                                keep_default_na=False, nrows=MAX_ROWS + 2)
    else:
        raise ValueError("支持 xlsx、xls、csv、tsv 表格")
    if raw.empty:
        raise ValueError("表格为空，至少需要一行列名")
    columns = [str(v).strip() for v in raw.iloc[0]]
    if any(not c for c in columns) or len(set(columns)) != len(columns):
        raise ValueError("列名存在空值或重复，请先修正表头")
    frame = raw.iloc[1:].copy().reset_index(drop=True)
    frame.columns = columns
    if len(frame) > MAX_ROWS:
        raise ValueError("表格超过 200000 行；未截断计算，请拆分或使用数据库")
    return frame


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or bool(pd.isna(value))


def _number(value) -> Decimal | None:
    if _blank(value):
        return None
    try:
        result = Decimal(str(value).strip())
        if not result.is_finite():
            raise InvalidOperation
        return result
    except InvalidOperation:
        raise ValueError(f"发现非数字值：{str(value)[:60]}；未将其按 0 计算") from None


def _day(value) -> date | None:
    if _blank(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.date() if isinstance(value, datetime) else value
    # Avoid interpreting integer IDs or Excel serials as nanosecond timestamps.
    if not isinstance(value, str) or not any(c in value for c in "-/年月"):
        raise ValueError("日期列须为 Excel 日期或明确的日期文本，不接受数字序号")
    try:
        return pd.Timestamp(value).date()
    except Exception:
        raise ValueError(f"无效日期：{str(value)[:60]}") from None


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if _blank(value):
        return None
    if isinstance(value, Decimal):
        return str(value)  # Exact decimal, no binary floating-point rounding.
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value.item() if hasattr(value, "item") else value


@tool
def inspect_table(filename: str) -> dict:
    """查看所有工作表的列名、完整行数、缺失数和 3 行样例；样例不可用于计算总额。"""
    try:
        path = session_file(filename)
        if path.suffix.lower() in {".xlsx", ".xls"}:
            with pd.ExcelFile(path) as book:
                names = book.sheet_names
        else:
            names = ["data"]
        sheets = []
        for name in names:
            frame = _frame(path, name)
            sheets.append({"sheet": name, "rows": len(frame), "columns": list(frame.columns),
                           "missing": {c: int(frame[c].map(_blank).sum()) for c in frame},
                           "sample": _clean(frame.head(3).to_dict("records"))})
        return {"status": "ok", "source": filename, "sheets": sheets}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@tool
def analyze_table(filename: str, sheet: str | None = None,
                  filters: list[dict] | None = None, group_by: list[str] | None = None,
                  metrics: list[dict] | None = None, date_column: str | None = None,
                  start_date: str | None = None, end_date: str | None = None,
                  offset: int = 0, limit: int = 100) -> dict:
    """对整张表筛选/分组/汇总，分页只限制输出，不限制计算。

    filters 全部 AND：{column,op,value}，op 支持 eq/ne/in/not_in/contains/not_contains/
    gt/gte/lt/lte/is_null/not_null；大小比较为数字比较，eq 为精确文本比较。
    metrics：{column,op,alias}，op 支持 sum/mean/min/max/count/distinct；
    column='*',op='count' 统计行数。金额/数量先调用工具汇总，禁止根据样例心算。
    group_by 为列名列表。date_column 配合 ISO start_date/end_date（两端含当日）。
    无 metrics 时返回筛选后的原始行，next_offset 非空则继续分页。
    无匹配数据返回 no_data，须报告实际日期覆盖，不能编造周报数值。
    """
    try:
        if offset < 0 or not 1 <= limit <= 500:
            raise ValueError("offset 须非负，limit 须为 1–500")
        frame = _frame(session_file(filename), sheet)
        total = len(frame)
        query = {"sheet": sheet, "filters": filters or [], "group_by": group_by or [],
                 "metrics": metrics or [], "date_column": date_column,
                 "start_date": start_date, "end_date": end_date}
        def column(name):
            if name not in frame.columns:
                raise ValueError(f"列不存在：{name}；可用列：{list(frame.columns)}")
            return frame[name]
        coverage = None
        warnings = []
        if (start_date or end_date) and not date_column:
            raise ValueError("日期筛选需要 date_column")
        if date_column:
            days = column(date_column).map(_day)
            valid = days.dropna()
            coverage = {"min": str(valid.min()) if len(valid) else None,
                        "max": str(valid.max()) if len(valid) else None,
                        "missing": int(days.isna().sum())}
            start = date.fromisoformat(start_date) if start_date else None
            end = date.fromisoformat(end_date) if end_date else None
            if start and end and start > end:
                raise ValueError("开始日期不能晚于结束日期")
            if start or end:
                frame = frame[days.map(lambda d: d is not None and not pd.isna(d)
                                       and (start is None or d >= start) and (end is None or d <= end))]
                if coverage["missing"]:
                    warnings.append(f"日期缺失的 {coverage['missing']} 行未参与日期筛选")
        for spec in filters or []:
            series = column(spec["column"])
            op, value = spec["op"], spec.get("value")
            texts = series.map(lambda v: None if _blank(v) else str(v))
            if op in {"eq", "ne", "in", "not_in"}:
                if op in {"in", "not_in"} and not isinstance(value, list):
                    raise ValueError("in/not_in 的 value 须为列表")
                values = value if op in {"in", "not_in"} else [value]
                mask = texts.isin([str(v) for v in values])
                if op in {"ne", "not_in"}:
                    mask = ~mask & texts.notna()
            elif op in {"contains", "not_contains"}:
                mask = texts.fillna("").str.contains(str(value), regex=False)
                if op == "not_contains":
                    mask = ~mask & texts.notna()
            elif op in {"is_null", "not_null"}:
                mask = texts.isna() if op == "is_null" else texts.notna()
            elif op in {"gt", "gte", "lt", "lte"}:
                threshold = _number(value)
                if threshold is None:
                    raise ValueError("数值比较需要非空 value")
                import operator
                compare = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}[op]
                mask = series.map(_number).map(lambda v: v is not None and compare(v, threshold))
            else:
                raise ValueError(f"不支持的筛选操作：{op}")
            frame = frame[mask]
        groups = group_by or []
        for name in groups:
            column(name)
        if groups and not metrics:
            raise ValueError("分组时需要 metrics")
        aliases = set(groups)
        for metric in metrics or []:
            name, op, alias = metric["column"], metric["op"], metric["alias"]
            if op not in {"sum", "mean", "min", "max", "count", "distinct"}:
                raise ValueError(f"不支持的汇总操作：{op}")
            if not alias or alias in aliases:
                raise ValueError("指标 alias 不可为空或与其他指标/分组重名")
            aliases.add(alias)
            if name == "*":
                if op != "count":
                    raise ValueError("* 仅用于 count")
            else:
                series = column(name)
                missing = int(series.map(_blank).sum())
                if missing:
                    warnings.append(f"{name} 有 {missing} 个空值，汇总忽略空值")
        matched = len(frame)
        rows = []
        if matched and metrics:
            grouped = frame.groupby(groups, dropna=False, sort=False) if groups else [((), frame)]
            for keys, part in grouped:
                keys = keys if isinstance(keys, tuple) else (keys,)
                row = dict(zip(groups, keys))
                for metric in metrics:
                    name, op, alias = metric["column"], metric["op"], metric["alias"]
                    if name == "*":
                        result = len(part)
                    else:
                        values = [v for v in part[name] if not _blank(v)]
                        if op == "count":
                            result = len(values)
                        elif op == "distinct":
                            result = len({str(v) for v in values})
                        else:
                            nums = [_number(v) for v in values]
                            result = None if not nums else {"sum": lambda: sum(nums, Decimal(0)),
                                "mean": lambda: sum(nums, Decimal(0)) / len(nums),
                                "min": lambda: min(nums), "max": lambda: max(nums)}[op]()
                    row[alias] = result
                rows.append(row)
        elif matched:
            rows = frame.to_dict("records")
        return {"status": "ok" if matched else "no_data", "source": filename, "query": query,
                "total_rows": total, "matched_rows": matched, "date_coverage": coverage,
                "warnings": warnings, "total_result_rows": len(rows), "offset": offset,
                "next_offset": offset + limit if offset + limit < len(rows) else None,
                "results": _clean(rows[offset:offset + limit])}
    except Exception as exc:
        return {"status": "error", "error": str(exc), "source": filename}
