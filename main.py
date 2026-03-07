#!/usr/bin/env python3
"""
TG Sender — точка входа.
Запуск: python main.py
"""
import sys
from pathlib import Path


def _bootstrap() -> None:
    """Проверяет наличие .env и sessions/, создаёт при необходимости."""
    env_file = Path(".env")
    sessions_dir = Path("sessions")

    sessions_dir.mkdir(exist_ok=True)

    if not env_file.exists():
        env_file.write_text(
            "API_ID=your_api_id_here\n"
            "API_HASH=your_api_hash_here\n",
            encoding="utf-8",
        )
        print(
            "\n  [!] Создан файл .env\n"
            "      Заполните API_ID и API_HASH, затем перезапустите.\n"
            "      Получить данные: https://my.telegram.org/apps\n"
        )
        sys.exit(0)

    # Quick sanity-check: values must not be placeholders
    from dotenv import dotenv_values
    env = dotenv_values(env_file)
    if env.get("API_ID", "").startswith("your_") or env.get("API_HASH", "").startswith("your_"):
        print(
            "\n  [!] .env не заполнен.\n"
            "      Укажите реальные API_ID и API_HASH в файле .env\n"
        )
        sys.exit(1)


if __name__ == "__main__":
    _bootstrap()
    from ui import main_menu
    main_menu()
