import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from scripts.eval_live import cases, grade, metrics, summarize
from api.monitor import MonitorCallbackHandler


class GradingTests(unittest.TestCase):
    def test_final_answer_not_incidental_number_is_graded(self):
        self.assertFalse(grade('来源共有 20 条。EVAL_RESULT {"value":"10"}', '20')[0])
        self.assertTrue(grade('EVAL_RESULT {"value":"20.00"}', '20')[0])
        self.assertFalse(grade('EVAL_RESULT {"value":"NaN"}', '20')[0])
        self.assertFalse(grade('EVAL_RESULT {"value":"20"} EVAL_RESULT {"value":"10"}', '20')[0])
        self.assertFalse(grade('EVAL_RESULT {"value":null}', '0')[0])

    def test_unknown_usage_and_review_timeout_are_not_success(self):
        events = [
            {"event": "model_usage", "data": {"usage": {"total_tokens": 12}}},
            {"event": "model_usage", "data": {"usage": None}},
            {"event": "review_timeout", "data": {}},
            {"event": "validation_result", "data": {"accepted": True, "review_requested": True}},
        ]
        result = metrics(events)
        self.assertIsNone(result['tokens'])
        self.assertEqual(result['observed_tokens'], 12)
        self.assertFalse(result['first_round_validator_pass'])
        self.assertFalse(result['final_validator_pass'])

    def test_failed_attempts_stay_in_denominator(self):
        m = metrics([])
        rows = [{"mode": "multi", "source": "database", "status": "completed", "numeric_correct": True, "seconds": 1, "metrics": m},
                {"mode": "multi", "source": "database", "status": "failed", "numeric_correct": False, "seconds": 10, "metrics": m}]
        self.assertEqual(summarize(rows, 2)['multi']['numeric_accuracy_all_attempts'], .5)
        self.assertEqual(summarize(rows, 2)['multi']['mean_seconds_all_attempts'], 5.5)

    def test_fifty_unique_questions_with_independent_oracles(self):
        dataset = cases()
        self.assertEqual(len({c['id'] for c in dataset}), 50)
        self.assertEqual(sum(c['source'] == 'database' for c in dataset), 25)
        self.assertTrue(all(c['oracle_sql'].startswith('SELECT ') for c in dataset if c['source'] == 'database'))
        self.assertTrue(all(c['expected'] is not None for c in dataset if c['source'] == 'attachment'))


class UsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_usage_from_provider_and_missing_usage(self):
        callback = MonitorCallbackHandler('usage_test')
        response = SimpleNamespace(generations=[[SimpleNamespace(message=SimpleNamespace(usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}))]])
        with patch('api.monitor.monitor.report', new_callable=AsyncMock) as report:
            await callback.on_llm_end(response, run_id='a')
            self.assertEqual(report.call_args.args[3]['usage']['total_tokens'], 5)
            await callback.on_llm_error(RuntimeError(), run_id='b')
            self.assertIsNone(report.call_args.args[3]['usage'])


if __name__ == '__main__':
    unittest.main()
