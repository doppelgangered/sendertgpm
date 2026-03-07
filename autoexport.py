"""
Автовыгруз сессий с vtmanagese.pro.
Скачивает ZIP, распаковывает только .session файлы в sessions/, .json игнорирует.
Может работать в фоне (цикличный режим) параллельно с основным UI.
"""
import asyncio
import io
import json
import logging
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import aiohttp

from config import SESSIONS_DIR

logger = logging.getLogger(__name__)

API_URL = "https://vtmanagese.pro/api/sessions"
CONFIG_FILE = Path("autoexport.json")

DEFAULT_CONFIG: dict = {
    "api_key": "",
    "tg_id": "",
    "interval": 300,  # секунды
}


# ── Config ────────────────────────────────────────────────────────────────────

def load_autoexport_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    return DEFAULT_CONFIG.copy()


def save_autoexport_config(cfg: dict) -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


# ── Core fetch ────────────────────────────────────────────────────────────────

class FetchResult:
    def __init__(self):
        self.added: int = 0        # новых .session файлов распаковано
        self.skipped: int = 0      # не-.session файлов пропущено
        self.error: str = ""
        self.timestamp: datetime = datetime.now()

    @property
    def ok(self) -> bool:
        return not self.error


async def fetch_once(api_key: str, tg_id: str) -> FetchResult:
    """
    Скачивает ZIP с сессиями и распаковывает только .session файлы в sessions/.
    .json и прочие файлы из архива игнорируются.
    """
    result = FetchResult()
    SESSIONS_DIR.mkdir(exist_ok=True)

    if not api_key or not tg_id:
        result.error = "API ключ или TG ID не заданы"
        return result

    headers = {"Authorization": f"Bearer {api_key}"}
    params = {"user_id": str(tg_id), "set_loaded": "true"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, headers=headers, params=params) as resp:
                if resp.status == 404:
                    result.error = "Сессий нет для данного пользователя (404)"
                    return result
                if resp.status != 200:
                    text = await resp.text()
                    result.error = f"Ошибка API: HTTP {resp.status} — {text[:120]}"
                    return result

                data = await resp.read()

        if len(data) < 30:
            result.error = "Сервер вернул пустой ответ"
            return result

        # Распаковываем ZIP в памяти — не сохраняем временный файл на диск
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for entry in zf.namelist():
                    filename = Path(entry).name  # убираем вложенные папки

                    if not filename.endswith(".session"):
                        result.skipped += 1
                        logger.debug(f"[autoexport] Пропущен файл: {entry}")
                        continue

                    dest = SESSIONS_DIR / filename
                    dest.write_bytes(zf.read(entry))
                    result.added += 1
                    logger.info(f"[autoexport] Сохранена сессия: {filename}")

        except zipfile.BadZipFile:
            result.error = "Ответ сервера не является ZIP-архивом"
            return result

    except aiohttp.ClientError as e:
        result.error = f"Ошибка соединения: {e}"
    except Exception as e:
        result.error = f"Неожиданная ошибка: {e}"

    return result


# ── Background loop ───────────────────────────────────────────────────────────

class AutoExportLoop:
    """Запускает цикличный выгруз в фоновом потоке."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_result: FetchResult | None = None
        self.iterations: int = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, api_key: str, tg_id: str, interval: int) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(api_key, tg_id, interval),
            daemon=True,
            name="autoexport-loop",
        )
        self._thread.start()
        logger.info(f"[autoexport] Цикл запущен (интервал {interval}с)")

    def stop(self) -> None:
        self._stop.set()
        logger.info("[autoexport] Цикл остановлен")

    def _loop(self, api_key: str, tg_id: str, interval: int) -> None:
        while not self._stop.is_set():
            self.last_result = asyncio.run(fetch_once(api_key, tg_id))
            self.iterations += 1
            if self.last_result.ok:
                logger.info(
                    f"[autoexport] Итерация {self.iterations}: "
                    f"+{self.last_result.added} сессий"
                )
            else:
                logger.warning(
                    f"[autoexport] Итерация {self.iterations}: "
                    f"ошибка — {self.last_result.error}"
                )
            self._stop.wait(interval)


# Глобальный экземпляр — используется из UI
loop_manager = AutoExportLoop()
