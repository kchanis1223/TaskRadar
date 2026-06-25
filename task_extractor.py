from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any

import requests

from agent_prompt import build_analysis_prompt
from date_utils import infer_datetime
from messenger_parser import parse_kakao_export
from models import AnalysisItem, AnalysisResult, ChatMessage
from reminder_generator import attach_reminders, build_morning_notification
from risk_scorer import score_miss_risk


REQUEST_KEYWORDS = ("제출", "정리", "공유", "확인", "봐주세요", "작성", "준비")
SCHEDULE_KEYWORDS = ("리허설", "회의", "미팅", "발표", "일정")
AMBIGUOUS_PHRASES = {
    "다음 주 초": "정확한 날짜가 불명확",
    "다음주 초": "정확한 날짜가 불명확",
    "퇴근 전": "제출 기준 시간이 불명확",
    "가능하면": "필수 여부와 우선순위가 불명확",
    "추후 공유": "후속 정보가 아직 미확정",
    "한번 봐주세요": "검토 범위가 불명확",
}


def analyze_text(raw_text: str, reference_date: date, senior_reply: str = "") -> AnalysisResult:
    messages = parse_kakao_export(raw_text)
    if not messages:
        messages = [ChatMessage(sender="사용자", message=line.strip()) for line in raw_text.splitlines() if line.strip()]
    return analyze_messages(messages, reference_date, senior_reply)


def analyze_messages(messages: list[ChatMessage], reference_date: date, senior_reply: str = "") -> AnalysisResult:
    for provider in (_analyze_with_gemma, _analyze_with_openai):
        try:
            result = provider(messages, reference_date, senior_reply)
            if result:
                return result
        except Exception:
            continue
    return _fallback_analyze(messages, reference_date, senior_reply)


def _analyze_with_gemma(messages: list[ChatMessage], reference_date: date, senior_reply: str) -> AnalysisResult | None:
    endpoint = os.getenv("GEMMA_API_URL")
    if not endpoint:
        return None
    prompt = build_analysis_prompt(messages, reference_date, senior_reply)
    response = requests.post(endpoint, json={"prompt": prompt}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    content = payload.get("content") or payload.get("text") or payload
    if isinstance(content, dict):
        data = content
    else:
        data = _load_json(str(content))
    return _result_from_provider_data(data, reference_date, "gemma")


def _analyze_with_openai(messages: list[ChatMessage], reference_date: date, senior_reply: str) -> AnalysisResult | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    client = OpenAI()
    prompt = build_analysis_prompt(messages, reference_date, senior_reply)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    content = response.choices[0].message.content or "{}"
    data = _load_json(content)
    return _result_from_provider_data(data, reference_date, "openai")


def _result_from_provider_data(data: dict[str, Any], reference_date: date, provider: str) -> AnalysisResult:
    items: list[AnalysisItem] = []
    for index, raw in enumerate(data.get("items", []), start=1):
        item = AnalysisItem(
            id=str(raw.get("id") or f"t{index}"),
            raw_text=str(raw.get("raw_text") or ""),
            type=raw.get("type") if raw.get("type") in ("일정", "할일", "확인필요") else "확인필요",
            title=str(raw.get("title") or "확인 필요 항목"),
            datetime_start=raw.get("datetime_start"),
            due=raw.get("due"),
            date_confidence=str(raw.get("date_confidence") or "중간"),
            classification=raw.get("classification") if raw.get("classification") in ("확정", "후보", "확인필요") else "후보",
            importance=str(raw.get("importance") or "중간"),
            ambiguities=list(raw.get("ambiguities") or []),
            suggested_question=str(raw.get("suggested_question") or ""),
            checklist=list(raw.get("checklist") or []),
        )
        score, level, risk_reasons = score_miss_risk(item.raw_text, item.due or item.datetime_start, reference_date)
        item.miss_risk_score = int(raw.get("miss_risk_score") or score)
        item.miss_risk_level = str(raw.get("miss_risk_level") or level)
        item.ambiguities = item.ambiguities or risk_reasons
        items.append(item)
    attach_reminders(items)
    notification = build_morning_notification(items)
    return AnalysisResult(
        summary=str(data.get("summary") or _build_summary(items)),
        reference_date=reference_date,
        items=items,
        recommended_messages=list(data.get("recommended_messages") or _build_recommended_messages(items)),
        questions_to_senior=str(data.get("questions_to_senior") or _combine_questions(items)),
        morning_notification_preview=notification,
        senior_reply_update="선배 답변을 반영해 결과를 업데이트했습니다." if data.get("senior_reply_update") else "",
        provider=provider,
    )


def _fallback_analyze(messages: list[ChatMessage], reference_date: date, senior_reply: str = "") -> AnalysisResult:
    items: list[AnalysisItem] = []
    for message in messages:
        text = message.message.strip()
        if not _looks_actionable(text):
            continue
        item_type = _classify_type(text)
        target_dt, confidence = infer_datetime(text, reference_date)
        item = AnalysisItem(
            id=f"t{len(items) + 1}",
            raw_text=text,
            type=item_type,
            title=_make_title(text, item_type),
            datetime_start=target_dt if item_type == "일정" else None,
            due=target_dt if item_type != "일정" else None,
            date_confidence=confidence,
            classification=_classification(item_type, confidence, text),
            importance="높음" if any(token in text for token in ["부탁", "제출", "발표", "내일"]) else "중간",
            ambiguities=_find_ambiguities(text),
            checklist=_make_checklist(text),
        )
        item.suggested_question = _make_question(item)
        score, level, risk_reasons = score_miss_risk(text, item.due or item.datetime_start, reference_date)
        item.miss_risk_score = score
        item.miss_risk_level = level
        item.ambiguities = list(dict.fromkeys(item.ambiguities + risk_reasons))
        items.append(item)

    if senior_reply.strip():
        _apply_senior_reply(items, senior_reply)

    attach_reminders(items)
    return AnalysisResult(
        summary=_build_summary(items),
        reference_date=reference_date,
        items=items,
        recommended_messages=_build_recommended_messages(items),
        questions_to_senior=_combine_questions(items),
        morning_notification_preview=build_morning_notification(items),
        senior_reply_update=_build_update_note(senior_reply) if senior_reply.strip() else "",
        provider="fallback",
    )


def _looks_actionable(text: str) -> bool:
    return any(keyword in text for keyword in REQUEST_KEYWORDS + SCHEDULE_KEYWORDS + tuple(AMBIGUOUS_PHRASES))


def _classify_type(text: str) -> str:
    if any(keyword in text for keyword in SCHEDULE_KEYWORDS) and any(token in text for token in ["시", "오전", "오후", "이번 주", "금요일"]):
        return "일정"
    if any(keyword in text for keyword in REQUEST_KEYWORDS):
        return "할일"
    return "확인필요"


def _classification(item_type: str, confidence: str, text: str) -> str:
    if _find_ambiguities(text):
        return "확인필요"
    if item_type == "일정" and confidence == "높음":
        return "확정"
    return "후보"


def _find_ambiguities(text: str) -> list[str]:
    return [reason for phrase, reason in AMBIGUOUS_PHRASES.items() if phrase in text]


def _make_title(text: str, item_type: str) -> str:
    if "리허설" in text:
        return "팀별 발표 리허설"
    if "발표자료" in text:
        return "발표자료 제출"
    if "아이디어" in text:
        return "AI Agent 아이디어 정리"
    if "양식" in text:
        return "제출 양식 확인"
    compact = re.sub(r"[.?!。]+$", "", text)
    return compact[:30] if compact else item_type


def _make_question(item: AnalysisItem) -> str:
    if "발표자료" in item.title:
        return "발표자료는 말씀주신 기한까지 제출드리겠습니다. 혹시 제출 양식과 공유 경로가 정해져 있을까요?"
    if "아이디어" in item.title:
        return "AI Agent 아이디어는 3개 정도 정리해 공유드리겠습니다. 표 형태로 핵심 문제와 기대 효과까지 정리하면 괜찮을까요?"
    if item.ambiguities:
        return f"{item.title} 관련해서 {item.ambiguities[0]} 부분을 확인드려도 될까요?"
    return f"{item.title} 내용으로 이해했습니다. 추가로 확인할 기준이 있을까요?"


def _make_checklist(text: str) -> list[str]:
    checklist = ["요청받은 기한 확인", "완료 후 공유 대상 확인"]
    if "발표자료" in text or "자료" in text:
        checklist += ["파일명에 이름/날짜 포함", "분량과 양식 확인", "오탈자 확인", "제출 경로 확인"]
    if "아이디어" in text:
        checklist += ["아이디어 개수 확인", "문제/해결/효과 구조로 정리", "공유 형식 확인"]
    return list(dict.fromkeys(checklist))


def _apply_senior_reply(items: list[AnalysisItem], senior_reply: str) -> None:
    details: dict[str, str] = {}
    if "PPT" in senior_reply.upper():
        details["양식"] = "PPT"
    page_match = re.search(r"(\d+)\s*장", senior_reply)
    if page_match:
        details["분량"] = f"{page_match.group(1)}장 이내"
    if "팀즈" in senior_reply or "과제방" in senior_reply:
        details["제출 경로"] = "팀즈 과제방"
    if "메일" in senior_reply:
        details["제출 경로"] = "메일"

    for item in items:
        if item.type in ("할일", "확인필요"):
            item.resolved_details.update(details)
            if details:
                item.ambiguities = [amb for amb in item.ambiguities if "미정" not in amb and "불명확" not in amb]
                item.classification = "후보" if item.classification == "확인필요" else item.classification
                item.checklist = list(dict.fromkeys(item.checklist + [f"{key}: {value}" for key, value in details.items()]))


def _build_summary(items: list[AnalysisItem]) -> str:
    if not items:
        return "분석 가능한 업무 요청이 발견되지 않았습니다."
    titles = ", ".join(item.title for item in items[:4])
    return f"{titles} 관련 업무 요청이 감지되었습니다."


def _build_recommended_messages(items: list[AnalysisItem]) -> list[str]:
    return [item.suggested_question for item in items if item.suggested_question]


def _combine_questions(items: list[AnalysisItem]) -> str:
    questions = _build_recommended_messages(items)
    if not questions:
        return "현재 추가 확인 질문은 없습니다."
    return "\n".join(f"- {question}" for question in questions)


def _build_update_note(senior_reply: str) -> str:
    return f"선배 답변을 반영했습니다: {senior_reply.strip()}"


def _load_json(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned)
    cleaned = re.sub(r"```$", "", cleaned).strip()
    return json.loads(cleaned)
