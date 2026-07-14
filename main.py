import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.config import LOG_DIR
from app.database import Base
from app.database import engine
from database.migrate import migrate
import models.company
import models.notification
import models.page
import models.opportunity
from app.cli import app


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
FILE_HANDLER_NAME = "quantagent-file"
CONSOLE_HANDLER_NAME = "quantagent-console"


def configure_logging(
    log_dir: Path = LOG_DIR,
    level_name: str | None = None,
) -> None:
    configured_level = (
        level_name or os.getenv("QUANTAGENT_LOG_LEVEL", "INFO")
    ).strip().upper()
    level = logging.getLevelNamesMapping().get(configured_level)
    if level is None:
        raise ValueError(
            "QUANTAGENT_LOG_LEVEL must be a valid Python logging level"
        )

    log_dir.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    formatter = logging.Formatter(LOG_FORMAT)
    handler_names = {handler.get_name() for handler in root_logger.handlers}

    if FILE_HANDLER_NAME not in handler_names:
        file_handler = TimedRotatingFileHandler(
            log_dir / "quantagent.log",
            when="midnight",
            backupCount=14,
            encoding="utf-8",
        )
        file_handler.set_name(FILE_HANDLER_NAME)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if CONSOLE_HANDLER_NAME not in handler_names:
        console_handler = logging.StreamHandler()
        console_handler.set_name(CONSOLE_HANDLER_NAME)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting QuantAgent")
    Base.metadata.create_all(bind=engine)
    migrate(engine)
    app()


if __name__ == "__main__":
    main()
