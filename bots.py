import random
from pathlib import Path

BOTS_FILE = Path("bots.txt")


def load_bots() -> list[str]:
    """Load bot usernames from bots.txt. Returns list of @username strings."""
    if not BOTS_FILE.exists():
        return []
    bots = []
    for line in BOTS_FILE.read_text(encoding="utf-8").splitlines():
        name = line.strip().lstrip("@")
        if name:
            bots.append("@" + name)
    return bots


def save_bots(bots: list[str]) -> None:
    BOTS_FILE.write_text(
        "\n".join(b.lstrip("@") for b in bots), encoding="utf-8"
    )


def random_bot(bots: list[str]) -> str | None:
    """Pick a random bot username, or None if list is empty."""
    return random.choice(bots) if bots else None


def apply_bot(text: str, bots: list[str]) -> str:
    """Replace all {bot} placeholders with a fresh random bot each time."""
    if "{bot}" not in text or not bots:
        return text
    # Each {bot} occurrence gets its own random pick
    while "{bot}" in text:
        text = text.replace("{bot}", random.choice(bots), 1)
    return text
