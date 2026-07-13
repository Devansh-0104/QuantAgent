from pathlib import Path


DATA_DIR = Path("data")
LOG_DIR = Path("logs")

DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)