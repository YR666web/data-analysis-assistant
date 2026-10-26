import unittest
from unittest.mock import Mock, patch

from tools.mysql_tools import list_drugs_by_antibiotic_status


class DrugCategoryQueryTests(unittest.TestCase):
    def run_query(self, antibiotics):
        cursor = Mock()
        cursor.fetchall.return_value = [
            {
                "generic_name": "测试药品",
                "brand_name": "测试商品名",
                "specifications": "10mg",
                "dosage_form": "片剂",
            }
        ]
        cursor.fetchone.return_value = {"count": 0}
        conn = Mock()
        conn.cursor.return_value = cursor
        with patch("tools.mysql_tools._get_connection", return_value=conn):
            answer = list_drugs_by_antibiotic_status(antibiotics=antibiotics)
        return answer, cursor, conn

    def test_antibiotic_query_uses_positive_category_filter(self):
        answer, cursor, conn = self.run_query(True)
        sql, params = cursor.execute.call_args_list[0].args
        self.assertIn("drug_class = %s", sql)
        self.assertEqual(params, ("抗生素",))
        self.assertIn("抗生素", answer)
        conn.close.assert_called_once()

    def test_non_antibiotic_query_uses_inverse_category_filter(self):
        answer, cursor, conn = self.run_query(False)
        sql, params = cursor.execute.call_args_list[0].args
        self.assertIn("drug_class = %s", sql)
        self.assertEqual(params, ("非抗生素",))
        self.assertIn("非抗生素", answer)
        self.assertIn("测试药品", answer)
        unknown_sql, unknown_params = cursor.execute.call_args_list[1].args
        self.assertIn("drug_class IS NULL OR drug_class NOT IN", unknown_sql)
        self.assertEqual(unknown_params, ("抗生素", "非抗生素"))
        conn.close.assert_called_once()

    def test_old_schema_fallback_is_explicitly_marked(self):
        class UnknownColumn(Exception):
            errno = 1054

        cursor = Mock()
        cursor.execute.side_effect = [UnknownColumn("unknown drug_class"), None]
        cursor.fetchall.return_value = [
            {"generic_name": "测试药品", "brand_name": None, "specifications": None, "dosage_form": None}
        ]
        conn = Mock()
        conn.cursor.return_value = cursor
        with patch("tools.mysql_tools._get_connection", return_value=conn):
            answer = list_drugs_by_antibiotic_status(antibiotics=False)
        self.assertIn("测试药品", answer)
        self.assertIn("旧版结果按治疗领域字段推断", answer)
        self.assertEqual(cursor.execute.call_count, 2)
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
