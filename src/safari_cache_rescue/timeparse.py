import re
from datetime import datetime, timedelta
from typing import Optional, Tuple


_DURATION = re.compile(r"^(\d+)([mhd])$")


def parse_duration(value: str) -> timedelta:
    match = _DURATION.fullmatch(value.strip().lower())
    if not match:
        raise ValueError("duration must use m, h, or d, for example 30m, 12h, or 2d")
    amount = int(match.group(1))
    if amount <= 0:
        raise ValueError("duration must be greater than zero")
    unit = match.group(2)
    return {
        "m": timedelta(minutes=amount),
        "h": timedelta(hours=amount),
        "d": timedelta(days=amount),
    }[unit]


def parse_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("time must be ISO 8601, for example 2026-08-23T09:00:00+08:00") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed


def resolve_window(
    since: Optional[str],
    start_value: Optional[str],
    end_value: Optional[str],
    default_since: Optional[str],
    now: Optional[datetime] = None,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    if since and (start_value or end_value):
        raise ValueError("--since cannot be combined with --from or --to")
    if end_value and not start_value:
        raise ValueError("--to requires --from")
    current = now or datetime.now().astimezone()
    if since or default_since:
        return current - parse_duration(since or default_since or ""), current
    if start_value:
        start = parse_datetime(start_value)
        end = parse_datetime(end_value) if end_value else current
        if start > end:
            raise ValueError("--from must not be later than --to")
        return start, end
    return None, None
