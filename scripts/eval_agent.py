"""Run 30 fixed, local tool-contract cases; never contacts an LLM provider."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api import context  # noqa: E402
from tools.table_tools import analyze_table, inspect_table  # noqa: E402
from tools.upload_file_read_tool import read_file_content  # noqa: E402


def matches(actual, expected) -> bool:
    """Subset comparison keeps rubric separate from irrelevant formatting."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and matches(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            matches(a, e) for a, e in zip(actual, expected)
        )
    return actual == expected


def create_fixture(directory: Path) -> None:
    sales = pd.DataFrame({
        "日期": ["2026-10-19"] * 7 + ["2026-10-26"],
        "分类": ["抗生素", "非抗生素"] * 4,
        "销售额": ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6", "100", "999"],
    })
    sales.to_csv(directory / "sales.csv", index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(directory / "multi.xlsx") as book:
        sales.to_excel(book, sheet_name="销售", index=False)
        sales.head(1).to_excel(book, sheet_name="说明", index=False)
    bad = sales.copy()
    bad.loc[7, "销售额"] = "未知"
    bad.to_csv(directory / "bad.csv", index=False, encoding="utf-8-sig")
    (directory / "brief.txt").write_text("ABCDEF", encoding="utf-8")


def evaluate() -> dict:
    cases = json.loads((ROOT / "eval" / "agent_cases.json").read_text(encoding="utf-8"))
    if len(cases) != 30 or len({c["id"] for c in cases}) != 30:
        raise ValueError("评测集必须包含 30 条唯一用例")
    records = []
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        create_fixture(directory)
        context.set_session("local_eval", temp)
        try:
            for case in cases:
                kind = case["kind"]
                started = time.perf_counter()
                try:
                    if kind == "inspect":
                        actual = inspect_table.invoke({"filename": "multi.xlsx", **case["args"]})
                    elif kind == "read":
                        actual = read_file_content.invoke(case["args"])
                    else:
                        filename = {"analyze_multi": "multi.xlsx", "analyze_bad": "bad.csv"}.get(kind, "sales.csv")
                        actual = analyze_table.invoke({"filename": filename, **case["args"]})
                    passed = matches(actual, case["expect"])
                except Exception as error:
                    actual, passed = {"unexpected_exception": type(error).__name__, "message": str(error)}, False
                elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
                records.append({"id": case["id"], "passed": passed, "latency_ms": elapsed_ms,
                                "expected": case["expect"], "actual": actual})
        finally:
            context.reset_session()
    latencies = [r["latency_ms"] for r in records]
    return {"suite": "agent-tool-contract-local-v1", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Local deterministic tool contracts with generated fixtures; no LLM or external API calls",
            "tool_contract_pass_rate": sum(r["passed"] for r in records) / len(records),
            "cases": len(records), "passed": sum(r["passed"] for r in records),
            "p50_latency_ms": statistics.median(latencies),
            "p95_latency_ms": sorted(latencies)[int((len(latencies) - 1) * 0.95)],
            "agent_task_completion_rate": None, "llm_accuracy": None,
            "llm_latency_ms": None, "llm_cost_usd": None,
            "records": records}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="保存完整 JSON 结果；默认只打印摘要")
    args = parser.parse_args()
    result = evaluate()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, ensure_ascii=False, indent=2))
    if not all(r["passed"] for r in result["records"]):
        for record in result["records"]:
            if not record["passed"]:
                print(f"FAIL {record['id']}: expected={record['expected']}, actual={record['actual']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
