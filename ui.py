import asyncio
import logging
from pathlib import Path

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from config import SESSIONS_DIR, load_settings, save_settings
from proxy_manager import load_proxies, save_proxies

console = Console()

TEXT_FILE = Path("text.txt")

BANNER = """\
 ████████╗ ██████╗     ███████╗███████╗███╗   ██╗██████╗ ███████╗██████╗
    ██╔══╝██╔════╝     ██╔════╝██╔════╝████╗  ██║██╔══██╗██╔════╝██╔══██╗
    ██║   ██║  ███╗    ███████╗█████╗  ██╔██╗ ██║██║  ██║█████╗  ██████╔╝
    ██║   ██║   ██║    ╚════██║██╔══╝  ██║╚██╗██║██║  ██║██╔══╝  ██╔══██╗
    ██║   ╚██████╔╝    ███████║███████╗██║ ╚████║██████╔╝███████╗██║  ██║
    ╚═╝    ╚═════╝     ╚══════╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚══════╝╚═╝  ╚═╝"""


def _header() -> Panel:
    return Panel(
        Text(BANNER, style="bold cyan", justify="center"),
        border_style="cyan",
        padding=(0, 1),
    )


def _status_table() -> Table:
    sessions = list(SESSIONS_DIR.glob("*.session")) if SESSIONS_DIR.exists() else []
    proxies = load_proxies()
    settings = load_settings()

    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    t.add_column(style="dim")
    t.add_column(style="bold white")

    t.add_row("Сессий найдено", str(len(sessions)))
    t.add_row("Прокси загружено", str(len(proxies)))
    text_status = (
        "[green]OK[/]" if TEXT_FILE.exists() else "[red]text.txt отсутствует[/]"
    )
    t.add_row("Шаблон (text.txt)", text_status)
    t.add_row(
        "Задержка",
        f"{settings['min_delay']}–{settings['max_delay']} сек / сообщ.",
    )
    t.add_row("Одновременно аккаунтов", str(settings.get("concurrent_accounts", 5)))
    return t


# ─── Main menu ───────────────────────────────────────────────────────────────

def main_menu() -> None:
    while True:
        console.clear()
        console.print(_header())
        console.print(_status_table())

        console.print()
        from autoexport import loop_manager
        loop_indicator = " [green]●[/]" if loop_manager.running else ""

        console.print("  [bold cyan]1.[/]  Запустить рассылку")
        console.print("  [bold cyan]2.[/]  Настройки")
        console.print("  [bold cyan]3.[/]  Прокси")
        console.print(f"  [bold cyan]4.[/]  Автовыгруз сессий{loop_indicator}")
        console.print("  [bold cyan]0.[/]  Выход")
        console.print()

        choice = Prompt.ask("  Выберите пункт", choices=["0", "1", "2", "3", "4"])

        if choice == "1":
            run_menu()
        elif choice == "2":
            settings_menu()
        elif choice == "3":
            proxy_menu()
        elif choice == "4":
            autoexport_menu()
        elif choice == "0":
            loop_manager.stop()
            console.print("\n[dim]До свидания.[/]\n")
            break


# ─── Run ─────────────────────────────────────────────────────────────────────

def run_menu() -> None:
    console.clear()
    console.print(_header())

    # Validate text.txt
    if not TEXT_FILE.exists():
        console.print(
            Panel(
                "[red]Файл [bold]text.txt[/bold] не найден.[/]\n"
                "Создайте его в корне проекта и добавьте текст рассылки.\n\n"
                "[dim]Поддерживается спинтакс: [bold]{Привет|Здравствуй} {мир|все}![/bold][/dim]",
                title="Ошибка",
                border_style="red",
            )
        )
        Prompt.ask("\n  Enter для возврата")
        return

    sessions = list(SESSIONS_DIR.glob("*.session")) if SESSIONS_DIR.exists() else []
    if not sessions:
        console.print(
            Panel(
                "[red]Нет сессий в папке [bold]sessions/[/bold][/]",
                title="Ошибка",
                border_style="red",
            )
        )
        Prompt.ask("\n  Enter для возврата")
        return

    # Preview template
    template = TEXT_FILE.read_text(encoding="utf-8").strip()
    from spintax import spin

    console.print(
        Panel(
            f"[dim]Шаблон:[/]\n{template}\n\n[dim]Пример спина:[/]\n[cyan]{spin(template)}[/]",
            title="text.txt",
            border_style="dim",
        )
    )

    proxies = load_proxies()
    settings = load_settings()

    console.print(f"\n  Сессий:  [bold]{len(sessions)}[/]")
    console.print(f"  Прокси:  [bold]{len(proxies)}[/]")
    console.print(
        f"  Задержка: [bold]{settings['min_delay']}–{settings['max_delay']}с[/] "
        f"между сообщениями, [bold]{settings['account_delay']}с[/] между аккаунтами"
    )

    if not Confirm.ask("\n  Запустить рассылку?"):
        return

    # Reset any previously attached handlers (re-entry guard)
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    # File handler
    file_handler = logging.FileHandler("sender.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
    )
    root_logger.addHandler(file_handler)

    # Console handler — Rich renders it cleanly alongside the Live progress bar
    from rich.logging import RichHandler
    console_handler = RichHandler(
        console=console,
        show_path=False,
        show_time=True,
        rich_tracebacks=False,
        markup=False,
    )
    console_handler.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)

    from sender import run_sender

    stats: dict = {}

    def _progress(s: dict) -> None:
        stats.update(s)

    console.print()

    # Live progress table
    def _make_progress_table(s: dict) -> Table:
        t = Table(box=box.ROUNDED, title="Прогресс рассылки", border_style="cyan")
        t.add_column("Метрика", style="dim")
        t.add_column("Значение", style="bold white", justify="right")
        done = s.get("accounts_done", 0)
        total = s.get("total", 0)
        pct = f"{done/total*100:.0f}%" if total else "—"
        t.add_row("Аккаунтов обработано", f"{done} / {total}  ({pct})")
        t.add_row("Отправлено", str(s.get("sent", 0)))
        t.add_row("Недоступно / ошибки", str(s.get("failed", 0)))
        t.add_row("Пропущено (неавторизованы)", str(s.get("skipped", 0)))
        flood = s.get("flood", 0)
        flood_str = f"[yellow]{flood}[/]" if flood else "[dim]0[/]"
        t.add_row("Флудвейт (сейчас в sessions/flood/)", flood_str)
        dead = s.get("errors", 0)
        dead_str = f"[red]{dead}[/]" if dead else str(dead)
        t.add_row("Мёртвых → sessions/dead/", dead_str)
        return t

    initial_stats: dict = {
        "sent": 0, "failed": 0, "skipped": 0,
        "errors": 0, "flood": 0, "accounts_done": 0, "total": len(sessions),
    }

    try:
        with Live(
            _make_progress_table(initial_stats),
            console=console,
            refresh_per_second=2,
        ) as live:
            def _live_progress(s: dict) -> None:
                stats.update(s)
                live.update(_make_progress_table(s))

            asyncio.run(run_sender(progress_callback=_live_progress))

    except FileNotFoundError as e:
        console.print(f"\n[red]{e}[/]")
        Prompt.ask("\n  Enter для возврата")
        return
    except ValueError as e:
        console.print(f"\n[red]{e}[/]")
        Prompt.ask("\n  Enter для возврата")
        return
    except KeyboardInterrupt:
        console.print("\n[yellow]Остановлено пользователем.[/]")

    # ── Post-send menu ────────────────────────────────────────────────────────
    _post_send_menu(stats, _make_progress_table)


def _post_send_menu(stats: dict, make_table) -> None:
    """Показывается сразу после завершения рассылки."""
    from sender import FLOOD_DIR

    while True:
        console.print("\n[bold green]Рассылка завершена![/]")
        console.print(make_table(stats))
        console.print("[dim]Подробный лог: sender.log[/]\n")

        flood_in_dir = len(list(FLOOD_DIR.glob("*.session"))) if FLOOD_DIR.exists() else 0

        console.print("  [bold cyan]1.[/]  Продолжить рассылку (запустить ещё раз)")
        released_str = f"[yellow]{flood_in_dir}[/] в flood/" if flood_in_dir else "[dim]0 в flood/[/]"
        console.print(f"  [bold cyan]2.[/]  Вернуть из флудвейта ({released_str})")
        console.print("  [bold cyan]0.[/]  Выйти в главное меню")
        console.print()

        choice = Prompt.ask("  Выберите", choices=["0", "1", "2"])

        if choice == "0":
            break

        elif choice == "1":
            # Перезапуск — возвращаемся в run_menu
            run_menu()
            break

        elif choice == "2":
            _restore_sessions_from(FLOOD_DIR, "sessions/flood/")
            # Обновляем счётчик flood в stats (сессии вышли вручную)
            still_in_flood = len(list(FLOOD_DIR.glob("*.session"))) if FLOOD_DIR.exists() else 0
            stats["flood"] = still_in_flood


# ─── Autoexport ──────────────────────────────────────────────────────────────

def autoexport_menu() -> None:
    from autoexport import (
        fetch_once, load_autoexport_config, loop_manager, save_autoexport_config,
    )
    from rich.progress import Progress, SpinnerColumn, TextColumn

    while True:
        console.clear()
        console.print(_header())

        cfg = load_autoexport_config()
        api_key  = cfg["api_key"]
        tg_id    = cfg["tg_id"]
        interval = cfg["interval"]

        key_display = (api_key[:6] + "…" + api_key[-4:]) if len(api_key) > 10 else (api_key or "[red]не задан[/]")

        t = Table(box=box.SIMPLE, title="Автовыгруз сессий", border_style="cyan")
        t.add_column("#", style="dim", justify="right")
        t.add_column("Параметр")
        t.add_column("Значение", style="cyan", justify="right")
        t.add_row("1", "API ключ", key_display)
        t.add_row("2", "Telegram ID", tg_id or "[red]не задан[/]")
        t.add_row("3", "Интервал (сек)", str(interval))

        status = "[green]● Запущен[/]" if loop_manager.running else "[dim]○ Остановлен[/]"
        t.add_row("", "Статус цикла", status)

        if loop_manager.last_result:
            lr = loop_manager.last_result
            ts = lr.timestamp.strftime("%H:%M:%S")
            if lr.ok:
                t.add_row("", "Последний выгруз", f"[green]+{lr.added} сессий[/] в {ts}")
            else:
                t.add_row("", "Последний выгруз", f"[red]{lr.error[:50]}[/]")
            t.add_row("", "Итераций выполнено", str(loop_manager.iterations))

        console.print(t)
        console.print()
        console.print("  [bold cyan]1–3.[/]  Изменить параметры")
        console.print("  [bold cyan]4.[/]    Выгрузить сейчас (однократно)")
        if loop_manager.running:
            console.print("  [bold cyan]5.[/]    [red]Остановить авто-цикл[/]")
        else:
            console.print("  [bold cyan]5.[/]    [green]Запустить авто-цикл[/]")
        console.print("  [bold cyan]0.[/]    Назад")
        console.print()

        choice = Prompt.ask("  Выберите", choices=["0", "1", "2", "3", "4", "5"])

        if choice == "0":
            break

        elif choice == "1":
            new_key = Prompt.ask("  API ключ", default=api_key)
            cfg["api_key"] = new_key.strip()
            save_autoexport_config(cfg)
            console.print("  [green]Сохранено.[/]")

        elif choice == "2":
            new_id = Prompt.ask("  Telegram ID", default=tg_id)
            cfg["tg_id"] = new_id.strip()
            save_autoexport_config(cfg)
            console.print("  [green]Сохранено.[/]")

        elif choice == "3":
            new_interval = IntPrompt.ask("  Интервал (сек)", default=interval)
            cfg["interval"] = new_interval
            save_autoexport_config(cfg)
            console.print("  [green]Сохранено.[/]")

        elif choice == "4":
            if not api_key or not tg_id:
                console.print("  [red]Заполните API ключ и Telegram ID.[/]")
                Prompt.ask("  Enter")
                continue

            with Progress(SpinnerColumn(), TextColumn("  Выгрузка…"), console=console, transient=True) as p:
                p.add_task("fetch")
                import asyncio as _asyncio
                result = _asyncio.run(fetch_once(api_key, tg_id))

            if result.ok:
                console.print(f"  [green]Готово! Добавлено сессий: {result.added}[/]  [dim](пропущено не-.session: {result.skipped})[/]")
            else:
                console.print(f"  [red]Ошибка: {result.error}[/]")
            Prompt.ask("  Enter")

        elif choice == "5":
            if loop_manager.running:
                loop_manager.stop()
                console.print("  [yellow]Цикл остановлен.[/]")
            else:
                if not api_key or not tg_id:
                    console.print("  [red]Заполните API ключ и Telegram ID.[/]")
                    Prompt.ask("  Enter")
                    continue
                loop_manager.start(api_key, tg_id, interval)
                console.print(f"  [green]Цикл запущен. Интервал: {interval}с[/]")
            Prompt.ask("  Enter")


# ─── Settings ─────────────────────────────────────────────────────────────────

def settings_menu() -> None:
    while True:
        console.clear()
        console.print(_header())

        settings = load_settings()

        auto_delete  = settings.get("auto_delete", False)
        scheduled    = settings.get("scheduled_messages", False)
        mutual_only  = settings.get("mutual_only", False)

        def _lbl(v: bool) -> str:
            return "[green]Включено[/]" if v else "[red]Выключено[/]"

        mutual_mode = (
            "[yellow]Только взаимные[/]" if mutual_only
            else "[dim]Взаимные + переписка[/]"
        )

        t = Table(box=box.SIMPLE, title="Настройки", border_style="cyan")
        t.add_column("#", style="dim", justify="right")
        t.add_column("Параметр")
        t.add_column("Значение", style="cyan", justify="right")
        t.add_row("1", "Мин. задержка между сообщениями (сек)", str(settings["min_delay"]))
        t.add_row("2", "Макс. задержка между сообщениями (сек)", str(settings["max_delay"]))
        t.add_row("3", "Задержка между аккаунтами (сек)", str(settings["account_delay"]))
        t.add_row("4", "Одновременно работающих аккаунтов", str(settings.get("concurrent_accounts", 5)))
        t.add_row("5", "Автоудаление у себя после отправки", _lbl(auto_delete))
        t.add_row("6", "Отложенные сообщения (+24ч, спинтакс)", _lbl(scheduled))
        t.add_row("7", "Режим цели рассылки", mutual_mode)

        from sender import DEAD_DIR, FLOOD_DIR
        dead_count  = len(list(DEAD_DIR.glob("*.session")))  if DEAD_DIR.exists()  else 0
        flood_count = len(list(FLOOD_DIR.glob("*.session"))) if FLOOD_DIR.exists() else 0
        dead_label  = f"[red]{dead_count}[/]"     if dead_count  else "[dim]0[/]"
        flood_label = f"[yellow]{flood_count}[/]" if flood_count else "[dim]0[/]"

        t.add_row("8", "Вернуть сессии из dead/  → sessions/", dead_label)
        t.add_row("9", "Вернуть сессии из flood/ → sessions/", flood_label)
        console.print(t)
        console.print()
        console.print("  [bold cyan]1–7.[/]  Изменить параметр")
        console.print("  [bold cyan]8.[/]    Восстановить мёртвые сессии")
        console.print("  [bold cyan]9.[/]    Вернуть сессии из флудвейта")
        console.print("  [bold cyan]0.[/]    Назад")
        console.print()

        choice = Prompt.ask("  Выберите", choices=["0","1","2","3","4","5","6","7","8","9"])

        if choice == "0":
            break
        elif choice == "1":
            settings["min_delay"] = IntPrompt.ask(
                "  Мин. задержка (сек)", default=settings["min_delay"]
            )
        elif choice == "2":
            settings["max_delay"] = IntPrompt.ask(
                "  Макс. задержка (сек)", default=settings["max_delay"]
            )
        elif choice == "3":
            settings["account_delay"] = IntPrompt.ask(
                "  Задержка между аккаунтами (сек)", default=settings["account_delay"]
            )
        elif choice == "4":
            settings["concurrent_accounts"] = IntPrompt.ask(
                "  Одновременно аккаунтов", default=settings.get("concurrent_accounts", 5)
            )
        elif choice == "5":
            settings["auto_delete"] = not auto_delete
            state = "[green]включено[/]" if settings["auto_delete"] else "[red]выключено[/]"
            console.print(f"  Автоудаление {state}")

        elif choice == "6":
            settings["scheduled_messages"] = not scheduled
            state = "[green]включено[/]" if settings["scheduled_messages"] else "[red]выключено[/]"
            console.print(f"  Отложенные сообщения {state}")

        elif choice == "7":
            settings["mutual_only"] = not mutual_only
            if settings["mutual_only"]:
                console.print("  Режим: [yellow]только взаимные контакты[/] (переписка не требуется)")
            else:
                console.print("  Режим: [dim]взаимные контакты + хотя бы 1 сообщение[/]")

        elif choice == "8":
            _restore_dead_sessions()
            continue

        elif choice == "9":
            from sender import FLOOD_DIR as _FD
            _restore_sessions_from(_FD, "sessions/flood/")
            continue

        if settings["min_delay"] > settings["max_delay"]:
            console.print("[yellow]  Предупреждение: мин. задержка больше макс.[/]")

        save_settings(settings)
        console.print("  [green]Сохранено.[/]")


# ─── Proxy ───────────────────────────────────────────────────────────────────

def proxy_menu() -> None:
    while True:
        console.clear()
        console.print(_header())

        proxies = load_proxies()

        t = Table(
            box=box.SIMPLE,
            title=f"Прокси SOCKS5  ([cyan]{len(proxies)}[/])",
            border_style="cyan",
        )
        t.add_column("#", style="dim", justify="right")
        t.add_column("Хост")
        t.add_column("Порт", justify="right")
        t.add_column("Пользователь")

        shown = proxies[:30]
        for i, p in enumerate(shown, 1):
            t.add_row(str(i), p["host"], str(p["port"]), p.get("username", "—"))
        if len(proxies) > 30:
            t.add_row("…", f"и ещё {len(proxies) - 30}", "", "")

        console.print(t)
        console.print()
        console.print("  [bold cyan]1.[/]  Добавить прокси вручную")
        console.print("  [bold cyan]2.[/]  Импортировать из файла (proxies.txt)")
        console.print("  [bold cyan]3.[/]  Удалить прокси по номеру")
        console.print("  [bold cyan]4.[/]  Очистить весь список")
        console.print("  [bold cyan]0.[/]  Назад")
        console.print()

        choice = Prompt.ask("  Выберите", choices=["0", "1", "2", "3", "4"])

        if choice == "0":
            break

        elif choice == "1":
            _add_proxy_dialog(proxies)

        elif choice == "2":
            _import_proxies_from_file(proxies)

        elif choice == "3":
            if not proxies:
                console.print("  [yellow]Список пуст.[/]")
                Prompt.ask("  Enter")
                continue
            idx = IntPrompt.ask(f"  Номер прокси (1–{len(proxies)})")
            if 1 <= idx <= len(proxies):
                removed = proxies.pop(idx - 1)
                save_proxies(proxies)
                console.print(
                    f"  [green]Удалён: {removed['host']}:{removed['port']}[/]"
                )
            else:
                console.print("  [red]Неверный номер.[/]")
            Prompt.ask("  Enter")

        elif choice == "4":
            if proxies and Confirm.ask("  Удалить все прокси?"):
                save_proxies([])
                console.print("  [green]Список очищен.[/]")
                proxies = []
            Prompt.ask("  Enter")


def _restore_sessions_from(src_dir: Path, label: str) -> None:
    import shutil

    if not src_dir.exists() or not list(src_dir.glob("*.session")):
        console.print(f"  [dim]В {src_dir}/ нет сессий.[/]")
        Prompt.ask("  Enter")
        return

    session_files = list(src_dir.glob("*.session"))
    console.print(f"\n  Найдено сессий в {label}: [bold]{len(session_files)}[/]")

    if not Confirm.ask("  Переместить все обратно в sessions/?"):
        return

    moved = 0
    for f in src_dir.glob("*.session*"):
        dest = SESSIONS_DIR / f.name
        try:
            shutil.move(str(f), str(dest))
            moved += 1
        except Exception as e:
            console.print(f"  [red]Ошибка при перемещении {f.name}: {e}[/]")

    console.print(f"  [green]Перемещено файлов: {moved}[/]")
    Prompt.ask("  Enter")


def _restore_dead_sessions() -> None:
    from sender import DEAD_DIR
    _restore_sessions_from(DEAD_DIR, "sessions/dead/")


def _import_proxies_from_file(existing: list[dict]) -> None:
    from config import PROXIES_FILE
    from proxy_validator import validate_proxies
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

    if not PROXIES_FILE.exists():
        console.print("  [yellow]Файл proxies.txt не найден в корне проекта.[/]")
        Prompt.ask("  Enter")
        return

    # Parse all lines
    candidates: list[dict] = []
    with open(PROXIES_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = _parse_proxy_line(line)
            if p:
                candidates.append(p)

    if not candidates:
        console.print("  [yellow]Файл пуст или не содержит корректных строк.[/]")
        Prompt.ask("  Enter")
        return

    # Deduplicate against already loaded proxies
    existing_keys = {(p["host"], p["port"]) for p in existing}
    new_only = [p for p in candidates if (p["host"], p["port"]) not in existing_keys]
    duplicates = len(candidates) - len(new_only)

    console.print(
        f"\n  Найдено в файле: [bold]{len(candidates)}[/]  "
        f"новых: [bold]{len(new_only)}[/]  "
        f"уже есть: [dim]{duplicates}[/]\n"
    )

    if not new_only:
        console.print("  [dim]Все прокси из файла уже добавлены.[/]")
        Prompt.ask("  Enter")
        return

    # Validate with live progress
    results: list[tuple] = []
    valid_count = 0
    fail_count = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("  Проверка прокси"),
        BarColumn(bar_width=30),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("[green]{task.fields[valid]}✓[/] [red]{task.fields[fail]}✗[/]"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("check", total=len(new_only), valid=0, fail=0)

        def _on_result(proxy, ok, latency, err, done, total):
            nonlocal valid_count, fail_count
            if ok:
                valid_count += 1
            else:
                fail_count += 1
            results.append((proxy, ok, latency, err))
            progress.update(task, advance=1, valid=valid_count, fail=fail_count)

        asyncio.run(validate_proxies(new_only, on_result=_on_result))

    # Results table
    console.print()
    t = Table(box=box.SIMPLE, title="Результаты валидации", border_style="cyan")
    t.add_column("Хост")
    t.add_column("Порт", justify="right")
    t.add_column("Статус", justify="center")
    t.add_column("Пинг", justify="right")
    t.add_column("Ошибка", style="dim")

    # Sort: valid first, then by latency
    results.sort(key=lambda r: (not r[1], r[2]))
    for proxy, ok, latency, err in results:
        status = "[green]OK[/]" if ok else "[red]FAIL[/]"
        ping = f"{latency:.0f} мс" if ok else "—"
        t.add_row(proxy["host"], str(proxy["port"]), status, ping, err[:60] if err else "")

    console.print(t)
    console.print(
        f"\n  Валидных: [green]{valid_count}[/]   "
        f"Недоступных: [red]{fail_count}[/]\n"
    )

    valid_proxies = [p for p, ok, *_ in results if ok]
    all_proxies = [p for p, *_ in results]

    if not valid_proxies:
        console.print("  [red]Ни один прокси не прошёл проверку.[/]")
        if fail_count and Confirm.ask("  Добавить все равно (без валидации)?", default=False):
            existing.extend(all_proxies)
            save_proxies(existing)
            console.print(f"  [yellow]Добавлено {len(all_proxies)} прокси (не валидированы).[/]")
        Prompt.ask("  Enter")
        return

    if fail_count:
        add_valid_only = Confirm.ask(
            f"  Добавить только валидные ({valid_count})?  "
            f"[dim]Нет = добавить все {len(new_only)}[/]",
            default=True,
        )
        to_add = valid_proxies if add_valid_only else all_proxies
    else:
        to_add = valid_proxies

    existing.extend(to_add)
    save_proxies(existing)
    console.print(f"  [green]Добавлено {len(to_add)} прокси.[/]")
    Prompt.ask("  Enter")


def _parse_proxy_line(line: str) -> dict | None:
    """Parse 'host:port' or 'host:port:user:pass'. Returns None on error."""
    parts = line.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        proxy: dict = {"host": parts[0], "port": int(parts[1])}
    except ValueError:
        return None
    if len(parts) == 4:
        proxy["username"] = parts[2]
        proxy["password"] = parts[3]
    return proxy


def _add_proxy_dialog(proxies: list[dict]) -> None:
    from proxy_validator import test_proxy

    console.print("\n  [dim]Формат: host:port  или  host:port:user:pass[/]")
    line = Prompt.ask("  Прокси").strip()

    proxy = _parse_proxy_line(line)
    if proxy is None:
        console.print("  [red]Неверный формат.[/]")
        Prompt.ask("  Enter")
        return

    addr = f"{proxy['host']}:{proxy['port']}"
    console.print(f"  Проверяем {addr} …", end="")

    ok, latency, err = asyncio.run(test_proxy(proxy))

    if ok:
        console.print(f"\r  [green]OK[/]  {addr}  [dim]{latency:.0f} мс[/]          ")
        proxies.append(proxy)
        save_proxies(proxies)
        console.print(f"  [green]Прокси добавлен.[/]")
    else:
        console.print(f"\r  [red]FAIL[/] {addr}  [dim]{err}[/]          ")
        if Confirm.ask("  Добавить всё равно?", default=False):
            proxies.append(proxy)
            save_proxies(proxies)
            console.print("  [yellow]Добавлен (не прошёл валидацию).[/]")

    Prompt.ask("  Enter")
