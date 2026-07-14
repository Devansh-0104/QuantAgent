import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class LoggingConfigurationTests(unittest.TestCase):
    def tearDown(self) -> None:
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if handler.get_name().startswith("quantagent-"):
                root_logger.removeHandler(handler)
                handler.close()

    def test_configure_logging_creates_file_and_reuses_handlers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_dir = Path(directory)
            main.configure_logging(log_dir=log_dir, level_name="WARNING")
            main.configure_logging(log_dir=log_dir, level_name="WARNING")

            handlers = [
                handler
                for handler in logging.getLogger().handlers
                if handler.get_name().startswith("quantagent-")
            ]

            self.assertEqual(len(handlers), 2)
            self.assertEqual(logging.getLogger().level, logging.WARNING)
            self.assertTrue((log_dir / "quantagent.log").exists())

    def test_configure_logging_rejects_invalid_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "QUANTAGENT_LOG_LEVEL"):
                main.configure_logging(
                    log_dir=Path(directory),
                    level_name="not-a-level",
                )


class ApplicationInitializationTests(unittest.TestCase):
    @patch("main.app")
    @patch("main.migrate")
    @patch("main.Base.metadata.create_all")
    @patch("main.configure_logging")
    def test_main_initializes_database_before_cli(
        self,
        configure_logging,
        create_all,
        migrate,
        app,
    ) -> None:
        manager = unittest.mock.Mock()
        manager.attach_mock(configure_logging, "configure_logging")
        manager.attach_mock(create_all, "create_all")
        manager.attach_mock(migrate, "migrate")
        manager.attach_mock(app, "app")

        main.main()

        self.assertEqual(
            [call[0] for call in manager.mock_calls],
            ["configure_logging", "create_all", "migrate", "app"],
        )


if __name__ == "__main__":
    unittest.main()
