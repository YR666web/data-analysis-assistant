import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import mysql.connector

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("drug_class_migration", ROOT / "scripts/migrate_drug_class.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class DrugClassMigrationTests(unittest.TestCase):
    def test_old_schema_check_only_reads_and_returns_pending(self):
        conn = Mock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [(1,), (0,)]
        with patch.object(migration.mysql.connector, "connect", return_value=conn), \
             patch.object(migration, "getpass") as passwords, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(migration.main(["--check"]), 2)
        self.assertTrue(all(c.args[0].startswith("SELECT ") for c in cursor.execute.call_args_list))
        conn.commit.assert_not_called()
        passwords.getpass.assert_not_called()
        conn.close.assert_called_once()

    def test_invalid_and_empty_categories_are_unclassified(self):
        conn = Mock()
        cursor = conn.cursor.return_value
        cursor.fetchone.side_effect = [(1,), (1,)]
        cursor.fetchall.return_value = [("抗生素", 2), ("非抗生素", 8), (None, 3), ("", 1), ("待核对", 2)]
        status = migration.inspect_schema(conn)
        self.assertEqual(status["unclassified"], 6)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(migration.print_status(status), 2)
        cursor.close.assert_called_once()

    def test_wrong_database_does_not_create_tables(self):
        conn = Mock()
        conn.cursor.return_value.fetchone.return_value = (0,)
        with self.assertRaisesRegex(ValueError, "没有 drugs 表"):
            migration.inspect_schema(conn)
        self.assertEqual(conn.cursor.return_value.execute.call_count, 1)

    def test_apply_requires_explicit_account_before_connecting(self):
        with patch.object(migration.mysql.connector, "connect") as connect, \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            migration.main(["--apply"])
        self.assertEqual(exc.exception.code, 2)
        connect.assert_not_called()

    def test_apply_consumes_all_results_before_committing(self):
        conn = Mock()
        cursor = conn.cursor.return_value
        cursor.with_rows = True
        cursor.nextset.side_effect = [True, True, None]
        migration.apply_migration(conn)
        cursor.execute.assert_called_once_with(migration.MIGRATION.read_text(encoding="utf-8"))
        self.assertEqual(cursor.fetchall.call_count, 3)
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
        cursor.close.assert_called_once()

    def test_error_in_later_statement_rolls_back_and_never_reports_success(self):
        conn = Mock()
        cursor = conn.cursor.return_value
        cursor.with_rows = False
        cursor.nextset.side_effect = mysql.connector.Error("UPDATE denied", errno=1142)
        with self.assertRaises(mysql.connector.Error):
            migration.apply_migration(conn)
        conn.commit.assert_not_called()
        conn.rollback.assert_called_once()
        cursor.close.assert_called_once()

    def test_apply_uses_prompted_password_without_changing_runtime_config(self):
        conn = Mock()
        ready = {"has_column": True, "counts": {"抗生素": 2, "非抗生素": 8}, "unclassified": 0}
        with patch.object(migration, "dotenv_values", return_value={"MYSQL_USER": "reader", "MYSQL_PASSWORD": "readonly-test"}), \
             patch.dict(migration.os.environ, {}, clear=True), \
             patch.object(migration.getpass, "getpass", return_value="temporary-test") as prompt, \
             patch.object(migration.mysql.connector, "connect", return_value=conn) as connect, \
             patch.object(migration, "inspect_schema", return_value=ready), \
             patch.object(migration, "apply_migration") as apply, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(migration.main(["--apply", "--user", "admin-test"]), 0)
        self.assertEqual(connect.call_args.kwargs["user"], "admin-test")
        self.assertEqual(connect.call_args.kwargs["password"], "temporary-test")
        self.assertFalse(connect.call_args.kwargs["autocommit"])
        self.assertNotIn("temporary-test", output.getvalue())
        prompt.assert_called_once()
        apply.assert_called_once_with(conn)
        conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
