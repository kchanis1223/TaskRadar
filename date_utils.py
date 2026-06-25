from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta


WEEKDAY_INDEX = {
    "월요일": 0,
    "화요일": 1,
    "수요일": 2,
    "목요일": 3,
    "금요일": 4,
    "토요일": 5,
    "일요일": 6,
    "월": 0,
    "화": 1,
    "수": 2,
    "목": 3,
    "금": 4,
    "토": 5,
    "일": 6,
}


def infer_datetime(text: str, reference_date: date) -> tuple[str | None, str]:
    inferred_date, confidence = infer_date(text, reference_date)
    if not inferred_date:
        return None, confidence
    inferred_time, time_confidence = infer_time(text)
    confidence = "낮음" if "낮음" in (confidence, time_confidence) else confidence
    return datetime.combine(inferred_date, inferred_time).isoformat(timespec="minutes"), confidence


def infer_date(text: str, reference_date: date) -> tuple[date | None, str]:
    if "내일" in text:
        return reference_date + timedelta(days=1), "높음"
    if "오늘" in text:
        return reference_date, "높음"
    if "다음 주 초" in text or "다음주 초" in text:
        days_until_next_monday = (7 - reference_date.weekday()) % 7
        days_until_next_monday = 7 if days_until_next_monday == 0 else days_until_next_monday
        return reference_date + timedelta(days=days_until_next_monday), "낮음"

    weekday_match = re.search(r"(이번 주\s*)?(월요일|화요일|수요일|목요일|금요일|토요일|일요일|월|화|수|목|금|토|일)", text)
    if weekday_match:
        target = WEEKDAY_INDEX[weekday_match.group(2)]
        delta = target - reference_date.weekday()
        if delta < 0 or "이번 주" not in text and delta == 0:
            delta += 7
        return reference_date + timedelta(days=delta), "높음"

    return None, "낮음"


def infer_time(text: str) -> tuple[time, str]:
    match = re.search(r"(오전|오후)?\s*(\d{1,2})시", text)
    if match:
        meridiem, hour_text = match.groups()
        hour = int(hour_text)
        if meridiem == "오후" and hour != 12:
            hour += 12
        if meridiem == "오전" and hour == 12:
            hour = 0
        return time(hour, 0), "높음"
    if "퇴근 전" in text:
        return time(18, 0), "낮음"
    if "오전" in text:
        return time(9, 0), "낮음"
    return time(9, 0), "낮음"
