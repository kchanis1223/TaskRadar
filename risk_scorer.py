from __future__ import annotations

from datetime import date, datetime


def score_miss_risk(text: str, due_or_start: str | None, reference_date: date) -> tuple[int, str, list[str]]:
    score = 0
    reasons: list[str] = []

    if due_or_start:
        try:
            target = datetime.fromisoformat(due_or_start)
            hours_left = (target - datetime.combine(reference_date, datetime.min.time())).total_seconds() / 3600
            if 0 <= hours_left <= 24:
                score += 30
                reasons.append("기한이 24시간 이내로 임박")
        except ValueError:
            pass

    if any(token in text for token in ["다음 주 초", "다음주 초", "퇴근 전", "가능하면"]):
        score += 20
        reasons.append("날짜/시간 또는 필수 여부가 불명확")
    if any(token in text for token in ["정리", "아이디어", "자료", "발표자료"]) and not any(token in text for token in ["양식", "PPT", "표", "분량"]):
        score += 20
        reasons.append("산출물 형식이 불명확")
    if any(token in text for token in ["제출", "공유"]) and not any(token in text for token in ["팀즈", "메일", "드라이브", "과제방"]):
        score += 15
        reasons.append("제출/공유 방식이 미정")
    if "추후 공유" in text or "추후" in text:
        score += 15
        reasons.append("후속 정보 대기")

    return min(score, 100), risk_level(score), reasons


def risk_level(score: int) -> str:
    if score >= 51:
        return "높음"
    if score >= 26:
        return "중간"
    return "낮음"
