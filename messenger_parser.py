from __future__ import annotations

import re
from datetime import datetime

from models import ChatMessage


DATE_LINE_RE = re.compile(r"-+\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일.*?-+")
BRACKET_RE = re.compile(r"^\[(?P<sender>[^\]]+)\]\s*(?:\[(?P<time>[^\]]+)\])?\s*(?P<message>.*)$")
COMMA_RE = re.compile(r"^(?P<sender>[^,]+),\s*(?P<time>(?:오전|오후)?\s*\d{1,2}:\d{2}),\s*(?P<message>.*)$")


def parse_kakao_export(text: str) -> list[ChatMessage]:
    """Parse common KakaoTalk exported txt formats into normalized messages."""
    messages: list[ChatMessage] = []
    current_date: tuple[int, int, int] | None = None
    last: ChatMessage | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip("\ufeff").rstrip()
        if not line.strip():
            continue

        date_match = DATE_LINE_RE.search(line)
        if date_match:
            current_date = tuple(int(part) for part in date_match.groups())
            last = None
            continue

        parsed = _parse_message_line(line, current_date)
        if parsed:
            messages.append(parsed)
            last = parsed
            continue

        if last:
            last.message = f"{last.message}\n{line.strip()}"

    return messages


def _parse_message_line(line: str, current_date: tuple[int, int, int] | None) -> ChatMessage | None:
    match = BRACKET_RE.match(line) or COMMA_RE.match(line)
    if not match:
        return None

    sender = match.group("sender").strip()
    time_text = (match.group("time") or "").strip()
    message = match.group("message").strip()
    timestamp = _parse_korean_time(current_date, time_text) if current_date and time_text else None
    return ChatMessage(sender=sender, timestamp=timestamp, message=message)


def _parse_korean_time(current_date: tuple[int, int, int], time_text: str) -> datetime | None:
    match = re.search(r"(오전|오후)?\s*(\d{1,2}):(\d{2})", time_text)
    if not match:
        return None
    meridiem, hour_text, minute_text = match.groups()
    hour = int(hour_text)
    minute = int(minute_text)
    if meridiem == "오후" and hour != 12:
        hour += 12
    if meridiem == "오전" and hour == 12:
        hour = 0
    return datetime(current_date[0], current_date[1], current_date[2], hour, minute)
