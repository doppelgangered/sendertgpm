import random
import re


def spin(text: str) -> str:
    """
    Process spintax in the given text and return a randomized result.

    Supported format:
      {option1|option2|option3}   — picks one option at random
      Nesting is supported: {Hello {world|there}|Hi {friend|buddy}}

    Example:
      "{Hello|Hi} {world|there}!" -> "Hi there!" (random each call)
    """
    # Keep replacing innermost {...} groups until none remain
    pattern = re.compile(r"\{([^{}]+)\}")
    while pattern.search(text):
        text = pattern.sub(lambda m: random.choice(m.group(1).split("|")), text)
    return text


def load_template(path: str = "text.txt") -> str:
    """Load the message template from a file."""
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def get_message(path: str = "text.txt") -> str:
    """Load template and apply spintax, returning a unique message variant."""
    template = load_template(path)
    return spin(template)
