from pathlib import Path
from unittest import TestCase
from unittest.mock import call, patch

from hermes_runtime import migration_bootstrap


class MigrationBootstrapTests(TestCase):
    def test_main_uses_runtime_store_and_applies_all_migrations_in_sorted_order(self):
        expected = sorted(
            Path(migration_bootstrap.__file__).parents[2]
            .joinpath("migrations")
            .glob("*.sql")
        )
        with patch.object(migration_bootstrap, "env_or_file", return_value="postgresql://example"), patch.object(
            migration_bootstrap, "PostgresRuntimeStore"
        ) as store_class:
            self.assertEqual(0, migration_bootstrap.main())

        store_class.assert_called_once_with("postgresql://example")
        self.assertEqual(
            [call(path) for path in expected],
            store_class.return_value.apply_migration.call_args_list,
        )

    def test_main_rejects_missing_database_dsn_before_constructing_store(self):
        with patch.object(migration_bootstrap, "env_or_file", return_value=""), patch.object(
            migration_bootstrap, "PostgresRuntimeStore"
        ) as store_class:
            with self.assertRaisesRegex(RuntimeError, "HERMES_DATABASE_URL_REQUIRED"):
                migration_bootstrap.main()

        store_class.assert_not_called()
