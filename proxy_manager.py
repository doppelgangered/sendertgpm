import socks

from config import PROXIES_FILE


def load_proxies() -> list[dict]:
    """
    Load proxies from proxies.txt.
    Supported formats (one per line):
      host:port
      host:port:username:password
    Lines starting with # are ignored.
    """
    if not PROXIES_FILE.exists():
        return []
    proxies: list[dict] = []
    with open(PROXIES_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 2:
                continue
            proxy: dict = {"host": parts[0], "port": int(parts[1])}
            if len(parts) == 4:
                proxy["username"] = parts[2]
                proxy["password"] = parts[3]
            proxies.append(proxy)
    return proxies


def save_proxies(proxies: list[dict]) -> None:
    with open(PROXIES_FILE, "w", encoding="utf-8") as f:
        for p in proxies:
            if "username" in p:
                f.write(f"{p['host']}:{p['port']}:{p['username']}:{p['password']}\n")
            else:
                f.write(f"{p['host']}:{p['port']}\n")


def assign_proxy(session_index: int, proxies: list[dict]) -> dict | None:
    """Round-robin: distributes proxies evenly across accounts."""
    if not proxies:
        return None
    return proxies[session_index % len(proxies)]


def proxy_to_telethon(proxy: dict | None) -> tuple | None:
    """Convert a proxy dict to the tuple format expected by Telethon."""
    if not proxy:
        return None
    if "username" in proxy:
        return (
            socks.SOCKS5,
            proxy["host"],
            proxy["port"],
            True,
            proxy["username"],
            proxy["password"],
        )
    return (socks.SOCKS5, proxy["host"], proxy["port"])
