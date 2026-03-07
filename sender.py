import asyncio
import logging
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.functions.contacts import GetContactsRequest
from telethon.errors import (
    AuthKeyError,
    FloodWaitError,
    PeerFloodError,
    SessionExpiredError,
    SessionRevokedError,
    UserDeactivatedBanError,
    UserDeactivatedError,
    UserIsBlockedError,
    UserPrivacyRestrictedError,
)
from telethon.tl.types import User

from config import SESSIONS_DIR, get_api_credentials, load_settings
from proxy_manager import assign_proxy, load_proxies, proxy_to_telethon
from spintax import spin

logger = logging.getLogger(__name__)

TEXT_FILE = Path("text.txt")
DEAD_DIR  = SESSIONS_DIR / "dead"
FLOOD_DIR = SESSIONS_DIR / "flood"

# Errors that mean the session/account is permanently unusable
_DEAD_ERRORS = (
    AuthKeyError,
    SessionExpiredError,
    SessionRevokedError,
    UserDeactivatedError,
    UserDeactivatedBanError,
)


# ── File helpers ──────────────────────────────────────────────────────────────

def _move_session(session_path: Path, target_dir: Path) -> Path:
    """
    Move all files belonging to a session (*.session, *.session-wal, etc.)
    to target_dir. Returns the new session path.
    Safe to call only when the TelegramClient is disconnected.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = session_path.name  # e.g. "acc123.session"
    for f in session_path.parent.glob(stem + "*"):
        dest = target_dir / f.name
        try:
            shutil.move(str(f), str(dest))
        except Exception as e:
            logger.error(f"Не удалось переместить {f.name} → {target_dir.name}/: {e}")
    new_path = target_dir / stem
    logger.debug(f"[{session_path.stem}] {session_path.parent.name}/ → {target_dir.name}/")
    return new_path


def _move_to_dead(session_path: Path) -> None:
    _move_session(session_path, DEAD_DIR)
    logger.warning(f"[{session_path.stem}] Сессия перемещена в sessions/dead/")


# ── Template ──────────────────────────────────────────────────────────────────

def load_text_template() -> str:
    if not TEXT_FILE.exists():
        raise FileNotFoundError(
            "Файл text.txt не найден. Создайте его в корне проекта."
        )
    template = TEXT_FILE.read_text(encoding="utf-8").strip()
    if not template:
        raise ValueError("Файл text.txt пустой.")
    return template


# ── Contact filter ────────────────────────────────────────────────────────────

async def get_eligible_contacts(
    client: TelegramClient, mutual_only: bool = False
) -> list[User]:
    """
    Returns eligible contacts for sending.
    mutual_only=False: взаимные контакты + хотя бы 1 сообщение в диалоге (default)
    mutual_only=True:  только взаимные контакты, история не проверяется
    """
    result = await client(GetContactsRequest(hash=0))
    mutual = [c for c in result.users if isinstance(c, User) and c.mutual_contact]

    if mutual_only:
        return mutual

    eligible: list[User] = []
    for contact in mutual:
        try:
            async for _ in client.iter_messages(contact, limit=1):
                eligible.append(contact)
                break
        except Exception as e:
            logger.debug(f"Пропуск контакта {contact.id}: {e}")

    return eligible


# ── Core account worker ───────────────────────────────────────────────────────

async def process_account(
    session_path: Path,
    session_index: int,
    template: str,
    proxies: list[dict],
    settings: dict,
    semaphore: asyncio.Semaphore,
    stats: dict,
    progress_callback=None,
) -> None:
    async with semaphore:
        api_id, api_hash = get_api_credentials()
        proxy        = assign_proxy(session_index, proxies)
        telethon_proxy = proxy_to_telethon(proxy)
        session_name = session_path.stem

        # current_path may change when session moves to flood/ and back
        current_path = session_path
        is_dead = False

        def _make_client(path: Path) -> TelegramClient:
            return TelegramClient(str(path), api_id, api_hash, proxy=telethon_proxy)

        client = _make_client(current_path)

        try:
            # ── Connect ───────────────────────────────────────────────────────
            proxy_str = (
                f"{proxy['host']}:{proxy['port']}" if proxy else "без прокси"
            )
            logger.info(f"[{session_name}] Подключение через {proxy_str}")
            try:
                await client.connect()
            except _DEAD_ERRORS as e:
                is_dead = True
                stats["errors"] += 1
                logger.error(f"[{session_name}] Мёртвая сессия при подключении: {e}")
                return
            except Exception as e:
                is_dead = True
                stats["errors"] += 1
                logger.error(f"[{session_name}] Не удалось подключиться: {e}")
                return

            # ── Auth ──────────────────────────────────────────────────────────
            try:
                authorized = await client.is_user_authorized()
            except _DEAD_ERRORS as e:
                is_dead = True
                stats["errors"] += 1
                logger.error(f"[{session_name}] Умерла при проверке авторизации: {e}")
                return

            if not authorized:
                is_dead = True
                stats["skipped"] += 1
                logger.warning(f"[{session_name}] Не авторизована → dead/")
                return

            # ── Send ──────────────────────────────────────────────────────────
            mutual_only = settings.get("mutual_only", False)
            contacts = await get_eligible_contacts(client, mutual_only=mutual_only)
            mode_str = "только взаимные" if mutual_only else "взаимные + переписка"
            logger.info(f"[{session_name}] Подходящих контактов: {len(contacts)} ({mode_str})")

            idx = 0
            while idx < len(contacts):
                contact = contacts[idx]
                message = spin(template)

                try:
                    sent = await client.send_message(contact, message)
                    stats["sent"] += 1
                    if progress_callback:
                        progress_callback(stats)
                    logger.info(
                        f"[{session_name}] -> {contact.id} ({contact.first_name})"
                    )

                    if settings.get("auto_delete"):
                        await client.delete_messages(contact, [sent.id], revoke=False)
                        logger.debug(
                            f"[{session_name}] Сообщение {sent.id} удалено у себя"
                        )

                    if settings.get("scheduled_messages"):
                        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=24)
                        scheduled_text = spin(template)
                        try:
                            await client.send_message(
                                contact,
                                scheduled_text,
                                schedule=scheduled_at,
                            )
                            logger.debug(
                                f"[{session_name}] Отложенное сообщение запланировано "
                                f"на {scheduled_at.strftime('%H:%M %d.%m.%Y')} UTC"
                            )
                        except Exception as e:
                            logger.warning(
                                f"[{session_name}] Не удалось запланировать сообщение: {e}"
                            )

                    delay = random.uniform(settings["min_delay"], settings["max_delay"])
                    await asyncio.sleep(delay)
                    idx += 1  # advance only on success

                except FloodWaitError as e:
                    wait_secs = e.seconds
                    logger.warning(
                        f"[{session_name}] FloodWait {wait_secs}s — "
                        f"перемещаем в sessions/flood/"
                    )

                    # Disconnect before touching the file
                    try:
                        await client.disconnect()
                    except Exception:
                        pass

                    current_path = _move_session(current_path, FLOOD_DIR)
                    stats["flood"] += 1
                    if progress_callback:
                        progress_callback(stats)

                    logger.info(
                        f"[{session_name}] Ожидание {wait_secs}с …"
                    )
                    await asyncio.sleep(wait_secs)

                    # Move back and reconnect
                    current_path = _move_session(current_path, SESSIONS_DIR)
                    stats["flood"] -= 1
                    if progress_callback:
                        progress_callback(stats)

                    client = _make_client(current_path)
                    try:
                        await client.connect()
                        logger.info(
                            f"[{session_name}] Флудвейт снят, продолжаем"
                        )
                    except Exception as e:
                        is_dead = True
                        stats["errors"] += 1
                        logger.error(
                            f"[{session_name}] Не удалось переподключиться после "
                            f"флудвейта: {e}"
                        )
                        break
                    # idx NOT incremented — retry same contact

                except PeerFloodError:
                    stats["failed"] += 1
                    logger.warning(
                        f"[{session_name}] PeerFlood — аккаунт временно заблокирован"
                    )
                    break

                except _DEAD_ERRORS as e:
                    is_dead = True
                    stats["errors"] += 1
                    logger.error(
                        f"[{session_name}] Сессия умерла во время рассылки: {e}"
                    )
                    break

                except (UserPrivacyRestrictedError, UserIsBlockedError):
                    stats["failed"] += 1
                    logger.debug(f"[{session_name}] Контакт {contact.id} недоступен")
                    idx += 1

                except Exception as e:
                    stats["failed"] += 1
                    logger.error(f"[{session_name}] Ошибка отправки: {e}")
                    idx += 1

        except _DEAD_ERRORS as e:
            is_dead = True
            stats["errors"] += 1
            logger.error(f"[{session_name}] Критическая ошибка (dead): {e}")

        except Exception as e:
            stats["errors"] += 1
            logger.error(f"[{session_name}] Критическая ошибка: {e}")

        finally:
            stats["accounts_done"] += 1
            if progress_callback:
                progress_callback(stats)
            try:
                await client.disconnect()
            except Exception:
                pass
            if is_dead:
                _move_to_dead(current_path)

        account_delay = settings.get("account_delay", 2)
        if account_delay > 0:
            await asyncio.sleep(account_delay)


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_sender(progress_callback=None) -> dict:
    settings = load_settings()
    proxies  = load_proxies()
    template = load_text_template()

    SESSIONS_DIR.mkdir(exist_ok=True)
    sessions = sorted(SESSIONS_DIR.glob("*.session"))
    if not sessions:
        raise ValueError("Сессии не найдены в папке sessions/")

    stats: dict = {
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "errors": 0,
        "flood": 0,
        "accounts_done": 0,
        "total": len(sessions),
    }

    semaphore = asyncio.Semaphore(settings.get("concurrent_accounts", 5))

    tasks = [
        process_account(
            session, i, template, proxies, settings, semaphore, stats, progress_callback
        )
        for i, session in enumerate(sessions)
    ]

    await asyncio.gather(*tasks, return_exceptions=True)
    return stats
