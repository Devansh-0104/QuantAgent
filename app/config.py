import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
SYNC_LOCK_PATH = DATA_DIR / "sync.lock"

load_dotenv(PROJECT_ROOT / ".env", override=False)

DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class EmailSettings:
    host: str
    port: int
    sender: str
    recipient: str
    username: str | None
    password: str | None
    use_tls: bool


def load_email_settings() -> EmailSettings | None:
    host = os.getenv("QUANTAGENT_SMTP_HOST", "").strip()
    sender = os.getenv("QUANTAGENT_EMAIL_FROM", "").strip()
    recipient = os.getenv("QUANTAGENT_EMAIL_TO", "").strip()
    if not host or not sender or not recipient:
        return None

    port_value = os.getenv("QUANTAGENT_SMTP_PORT", "587")
    try:
        port = int(port_value)
    except ValueError as exc:
        raise ValueError("QUANTAGENT_SMTP_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError("QUANTAGENT_SMTP_PORT must be between 1 and 65535")

    username_value = os.getenv("QUANTAGENT_SMTP_USERNAME", "").strip()
    password_value = os.getenv("QUANTAGENT_SMTP_PASSWORD", "").strip()
    if host.casefold() == "smtp.gmail.com":
        password_value = password_value.replace(" ", "")
    username = username_value or None
    password = password_value or None
    if bool(username) != bool(password):
        raise ValueError(
            "QUANTAGENT_SMTP_USERNAME and QUANTAGENT_SMTP_PASSWORD "
            "must be configured together"
        )

    use_tls = os.getenv("QUANTAGENT_SMTP_TLS", "true").casefold() not in {
        "0",
        "false",
        "no",
    }
    return EmailSettings(
        host=host,
        port=port,
        sender=sender,
        recipient=recipient,
        username=username,
        password=password,
        use_tls=use_tls,
    )
