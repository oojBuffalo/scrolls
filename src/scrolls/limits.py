"""Result caps share one range across Python slicing and SQLite LIMIT."""

MAX_LIMIT = 2**63 - 1


def validate_limit(value: int | str) -> int:
    """Parse a CLI count or validate an API count; zero requests no rows."""
    message = f"limit must be an integer between 0 and {MAX_LIMIT}"
    try:
        limit = int(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise ValueError(message) from exc
    if type(limit) is not int or not 0 <= limit <= MAX_LIMIT:
        raise ValueError(message)
    return limit
