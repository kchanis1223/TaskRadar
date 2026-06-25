from __future__ import annotations

from datetime import datetime, timedelta

from models import AnalysisItem


def attach_reminders(items: list[AnalysisItem]) -> None:
    for item in items:
        target_text = item.due or item.datetime_start
        if not target_text:
            item.reminders = ["확인 필요: 선배 답변을 받은 뒤 리마인드 설정"]
            continue
        target = datetime.fromisoformat(target_text)
        if item.type == "일정":
            item.reminders = [
                (target - timedelta(days=1)).isoformat(timespec="minutes"),
                (target - timedelta(hours=1)).isoformat(timespec="minutes"),
            ]
        elif item.type == "할일":
            item.reminders = [
                (target - timedelta(days=1)).replace(hour=9, minute=0).isoformat(timespec="minutes"),
                target.replace(hour=max(target.hour - 2, 9), minute=0).isoformat(timespec="minutes"),
            ]


def build_morning_notification(items: list[AnalysisItem]) -> str:
    todos = [item for item in items if item.type in ("할일", "확인필요")]
    if not todos:
        return "오늘 오전 8시 알림: 오늘 확인할 To-do가 없습니다."

    lines = ["오늘 오전 8시 알림 미리보기", ""]
    for index, item in enumerate(todos, start=1):
        due = item.due or item.datetime_start or "기한 확인 필요"
        lines.append(f"{index}. {item.title} ({due})")
        if item.ambiguities:
            lines.append(f"   - 확인 필요: {', '.join(item.ambiguities)}")
    return "\n".join(lines)
