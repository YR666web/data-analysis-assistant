import unittest

from tools.reflect_check import hard_check


class ReflectionTests(unittest.TestCase):
    def test_explicit_negative_pdf_request_does_not_force_pdf(self):
        from agent.main_agent import requests_pdf
        for query in ["生成简短报告，不需要 PDF", "不要生成pdf", "无需导出 PDF 文件", "不用PDF，只要Markdown"]:
            with self.subTest(query=query):
                self.assertFalse(requests_pdf(query))
        self.assertTrue(requests_pdf("请生成 PDF 报告"))
        self.assertTrue(requests_pdf("不需要PDF", explicit=True))
        self.assertTrue(requests_pdf("不要 PDF 初稿，但最终需要 PDF 报告"))

    def test_short_answer_does_not_need_report_length(self):
        self.assertEqual(hard_check({"report": "答案是 42。", "require_report": False}), [])

    def test_placeholder_word_in_short_answer_is_not_a_report_failure(self):
        self.assertEqual(hard_check({"report": "用户问了 TODO 的含义。", "require_report": False}), [])

    def test_empty_answer_is_rejected(self):
        self.assertIn("没有生成可展示的回答", hard_check({"report": " "}))

    def test_no_data_report_does_not_trigger_padding_retry(self):
        report = "# 销售周报\n统计周期：2026-10-19 至 2026-10-25。\n无匹配数据；现有数据仅覆盖 2025 年，无法计算本周销售额。"
        self.assertEqual(hard_check({"report": report, "require_report": True}), [])

    def test_required_pdf_must_exist(self):
        issues = hard_check({"report": "内容" * 400, "require_report": True, "require_pdf": True})
        self.assertIn("未生成要求的 PDF 文件", issues)

    def test_unstructured_source_mentions_do_not_force_retries(self):
        issues = hard_check({
            "report": "简短的有效回答",
            "require_report": False,
            "required_sources": ["knowledge", "db_query"],
            "called_sources": [],
        })
        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
