from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal


Classification = Literal["확정", "후보", "확인필요"]
ItemType = Literal["일정", "할일", "확인필요"]


@dataclass
class ChatMessage:
    sender: str
    message: str
    timestamp: datetime | None = None


@dataclass
class AnalysisItem:
    id: str
    raw_text: str
    type: ItemType
    title: str
    datetime_start: str | None = None
    due: str | None = None
    date_confidence: str = "중간"
    classification: Classification = "후보"
    importance: str = "중간"
    miss_risk_score: int = 0
    miss_risk_level: str = "낮음"
    ambiguities: list[str] = field(default_factory=list)
    suggested_question: str = ""
    reminders: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)
    resolved_details: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "raw_text": self.raw_text,
            "type": self.type,
            "title": self.title,
            "datetime_start": self.datetime_start,
            "due": self.due,
            "date_confidence": self.date_confidence,
            "classification": self.classification,
            "importance": self.importance,
            "miss_risk_score": self.miss_risk_score,
            "miss_risk_level": self.miss_risk_level,
            "ambiguities": self.ambiguities,
            "suggested_question": self.suggested_question,
            "reminders": self.reminders,
            "checklist": self.checklist,
            "resolved_details": self.resolved_details,
        }


@dataclass
class AnalysisResult:
    summary: str
    reference_date: date
    items: list[AnalysisItem]
    recommended_messages: list[str]
    questions_to_senior: str
    morning_notification_preview: str
    senior_reply_update: str = ""
    provider: str = "fallback"

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "reference_date": self.reference_date.isoformat(),
            "items": [item.to_dict() for item in self.items],
            "recommended_messages": self.recommended_messages,
            "questions_to_senior": self.questions_to_senior,
            "morning_notification_preview": self.morning_notification_preview,
            "senior_reply_update": self.senior_reply_update,
            "provider": self.provider,
        }
