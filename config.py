import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SESSIONS_DIR = Path("sessions")
PROXIES_FILE = Path("proxies.txt")
SETTINGS_FILE = Path("settings.json")

DEFAULT_SETTINGS: dict = {
    "min_delay": 5,
    "max_delay": 15,
    "account_delay": 2,
    "concurrent_accounts": 5,
    "message": "",
    "auto_delete": False,
    "scheduled_messages": False,
}


def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)


def get_api_credentials() -> tuple[int, str]:
    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    if not api_id or not api_hash:
        raise ValueError("API_ID и API_HASH не найдены в .env файле")
    return int(api_id), api_hash
