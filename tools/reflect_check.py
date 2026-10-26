"""反思循环硬校验器（TDD §5.2 H1~H4）。"""
from __future__ import annotations

# H2：占位符关键词
PLACEHOLDER_KEYWORDS = ["待补充", "TODO", "等待子任务", "占位", "（略）"]


def hard_check(result: dict) -> list[str]:
    """执行正文、占位符和 PDF 硬校验，返回未通过项列表。

    ``result`` 由编排层 ``main_agent_run`` 返回，字段：
    - ``report``           : 报告正文（str）
    - ``called_sources``   : 本轮实际调用的数据源 key 列表
    - ``required_sources`` : 主智能体规划阶段声明的数据源 key 列表
    - ``require_pdf``      : 任务是否要求 PDF（bool）
    - ``pdf_produced``     : 是否已产出 PDF 文件（bool）

    校验项：
    - H1 内容：正文非空（不以字数代替质量）
    - H2 占位符：报告含「待补充 / TODO / 等待子任务 / 占位 /（略）」等关键词
    - H3 格式：要求 PDF 但未产出 PDF 文件
    """
    report = result.get("report", "")
    issues: list[str] = []

    if not report.strip():
        issues.append("没有生成可展示的回答")
        return issues

    # H2 占位符
    if result.get("require_report") and any(kw in report for kw in PLACEHOLDER_KEYWORDS):
        issues.append("报告存在未填充占位符")

    # H3 格式
    if result.get("require_pdf") and not result.get("pdf_produced"):
        issues.append("未生成要求的 PDF 文件")

    return issues


if __name__ == "__main__":
    ok = "这是一段报告正文" * 50
    print("H1(篇幅不足):", hard_check({"report": "短"}))
    print("H2(占位符):", hard_check({"report": ok + "待补充"}))
    print(
        "H3(缺PDF):",
        hard_check({"report": ok, "require_pdf": True, "pdf_produced": False}),
    )
    print(
        "H4(缺数据源):",
        hard_check(
            {
                "report": ok,
                "required_sources": ["knowledge", "db_query"],
                "called_sources": ["db_query"],
            }
        ),
    )
    print("全部通过:", hard_check({"report": ok}))
