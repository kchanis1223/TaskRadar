from __future__ import annotations

import json
import copy
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from agent_prompt import build_analysis_prompt, build_senior_reply_patch_prompt
from config import load_local_env
from date_utils import infer_datetime
from messenger_parser import parse_kakao_export
from models import AnalysisItem, AnalysisResult, ChatMessage
from reminder_generator import attach_reminders, build_morning_notification
from risk_scorer import score_miss_risk


REQUEST_KEYWORDS = ("제출", "정리", "공유", "확인", "봐주세요", "작성", "준비")
SCHEDULE_KEYWORDS = ("리허설", "회의", "미팅", "발표", "일정")
TIME_HINT_PATTERN = re.compile(
    r"(오늘|내일|모레|이번\s*주|다음\s*주|다음주|월요일|화요일|수요일|목요일|금요일|토요일|일요일|"
    r"오전|오후|\d{1,2}\s*시|\d{1,2}\s*분|\d{1,2}\s*/\s*\d{1,2}|"
    r"\d{4}-\d{1,2}-\d{1,2}|까지|전까지|마감|기한|퇴근\s*전)"
)
AMBIGUOUS_PHRASES = {
    "다음 주 초": "정확한 날짜가 불명확",
    "다음주 초": "정확한 날짜가 불명확",
    "퇴근 전": "제출 기준 시간이 불명확",
    "가능하면": "필수 여부와 우선순위가 불명확",
    "추후 공유": "후속 정보가 아직 미확정",
    "한번 봐주세요": "검토 범위가 불명확",
}


ReferenceTime = date | datetime


def analyze_text(raw_text: str, reference_date: ReferenceTime, senior_reply: str = "") -> AnalysisResult:
    load_local_env()
    messages = parse_kakao_export(raw_text)
    if not messages:
        messages = [ChatMessage(sender="사용자", message=line.strip()) for line in raw_text.splitlines() if line.strip()]
    return analyze_messages(messages, reference_date, senior_reply)


def analyze_messages(messages: list[ChatMessage], reference_date: ReferenceTime, senior_reply: str = "") -> AnalysisResult:
    load_local_env()
    provider_errors: list[str] = []
    providers = (
        (_analyze_with_opencode_cli,)
        if _truthy_env("TASKRADAR_REQUIRE_OPENCODE")
        else (_analyze_with_opencode_cli, _analyze_with_openai, _analyze_with_anthropic, _analyze_with_gemma)
    )

    for provider in providers:
        try:
            result = provider(messages, reference_date, senior_reply)
            if result:
                result.warnings.extend(provider_errors)
                return result
        except Exception as exc:
            provider_errors.append(_format_provider_error(provider.__name__, exc))
            continue

    if _truthy_env("TASKRADAR_REQUIRE_OPENCODE"):
        return _opencode_unavailable_result(reference_date, provider_errors)

    result = _fallback_analyze(messages, reference_date, senior_reply)
    if provider_errors:
        result.provider_error = "AI provider 연결 실패로 규칙 기반 폴백 분석을 사용했습니다."
        result.warnings = provider_errors
    return result


def update_result_with_senior_reply(
    result: AnalysisResult,
    senior_reply: str,
    target_item_ids: list[str] | None = None,
) -> AnalysisResult:
    if not senior_reply.strip():
        return copy.deepcopy(result)

    if _truthy_env("TASKRADAR_USE_OPENCODE"):
        try:
            updated = _update_result_with_opencode_patch(result, senior_reply, target_item_ids)
        except Exception as exc:
            updated = copy.deepcopy(result)
            _apply_senior_reply(updated.items, senior_reply, updated.reference_date, target_item_ids)
            updated.provider_error = "AI 업데이트 연결이 원활하지 않아 임시 로컬 반영을 사용했습니다."
            updated.warnings = list(dict.fromkeys(updated.warnings + [_format_provider_error("opencode_patch", exc)]))
            updated.provider = f"{updated.provider}+local-update"
        else:
            updated.provider = f"{updated.provider}+opencode-patch"
    else:
        updated = copy.deepcopy(result)
        _apply_senior_reply(updated.items, senior_reply, updated.reference_date, target_item_ids)
        updated.provider = f"{updated.provider}+local-update"

    attach_reminders(updated.items)
    updated.recommended_messages = _build_recommended_messages(updated.items)
    updated.questions_to_senior = _combine_questions(updated.items)
    updated.morning_notification_preview = build_morning_notification(updated.items)
    if not updated.senior_reply_update:
        updated.senior_reply_update = _build_update_note(senior_reply)
    return updated


def _update_result_with_opencode_patch(
    result: AnalysisResult,
    senior_reply: str,
    target_item_ids: list[str] | None,
) -> AnalysisResult:
    load_local_env()
    if not _truthy_env("TASKRADAR_USE_OPENCODE"):
        raise RuntimeError("opencode patch provider is disabled")

    selected_items = _selected_items_for_patch(result.items, target_item_ids)
    if not selected_items:
        raise RuntimeError("no selected items for patch")

    prompt = build_senior_reply_patch_prompt(
        selected_items=[item.to_dict() for item in selected_items],
        senior_reply=senior_reply,
        reference_date=result.reference_date,
    )
    data = _run_opencode_json(
        prompt,
        title="TaskRadar Senior Reply Patch",
        instruction="첨부된 선배 답변 업데이트 프롬프트를 처리하고 JSON patch 객체 하나만 출력하세요.",
    )

    updated = copy.deepcopy(result)
    _merge_update_patch(updated.items, data, {item.id for item in selected_items})
    updated.senior_reply_update = str(data.get("senior_reply_update") or _build_update_note(senior_reply))
    updated.provider_error = ""
    return updated


def _selected_items_for_patch(items: list[AnalysisItem], target_item_ids: list[str] | None) -> list[AnalysisItem]:
    actionable = [item for item in items if item.type in ("일정", "할일", "확인필요")]
    explicit_ids = set(target_item_ids or [])
    if explicit_ids:
        return [item for item in actionable if item.id in explicit_ids]
    return actionable


def _messages_for_provider(messages: list[ChatMessage]) -> list[ChatMessage]:
    if not messages or not _truthy_env("TASKRADAR_COMPRESS_INPUT", default=True):
        return messages

    max_messages = int(os.getenv("TASKRADAR_MAX_PROVIDER_MESSAGES", "40"))
    context_radius = int(os.getenv("TASKRADAR_PROVIDER_CONTEXT_RADIUS", "1"))
    candidate_indexes = {
        index
        for index, message in enumerate(messages)
        if _looks_provider_relevant(message.message)
    }
    if not candidate_indexes:
        return messages[-min(len(messages), max_messages):]

    expanded_indexes: set[int] = set()
    for index in candidate_indexes:
        start = max(0, index - context_radius)
        end = min(len(messages), index + context_radius + 1)
        expanded_indexes.update(range(start, end))

    selected_indexes = sorted(expanded_indexes)
    if len(selected_indexes) > max_messages:
        candidate_window = sorted(candidate_indexes)
        trimmed: list[int] = []
        for index in candidate_window:
            for near_index in range(max(0, index - context_radius), min(len(messages), index + context_radius + 1)):
                if near_index not in trimmed:
                    trimmed.append(near_index)
                if len(trimmed) >= max_messages:
                    break
            if len(trimmed) >= max_messages:
                break
        selected_indexes = sorted(trimmed)

    if len(selected_indexes) >= len(messages):
        return messages

    return [messages[index] for index in selected_indexes]


def _looks_provider_relevant(text: str) -> bool:
    return _looks_actionable(text) or bool(TIME_HINT_PATTERN.search(text))


def _analyze_with_gemma(messages: list[ChatMessage], reference_date: ReferenceTime, senior_reply: str) -> AnalysisResult | None:
    endpoint = os.getenv("GEMMA_API_URL")
    if not endpoint:
        return None
    prompt = build_analysis_prompt(_messages_for_provider(messages), reference_date, senior_reply)
    response = requests.post(endpoint, json={"prompt": prompt}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    content = payload.get("content") or payload.get("text") or payload
    if isinstance(content, dict):
        data = content
    else:
        data = _load_json(str(content))
    return _result_from_provider_data(data, reference_date, "gemma", senior_reply)


def _analyze_with_opencode_cli(messages: list[ChatMessage], reference_date: ReferenceTime, senior_reply: str) -> AnalysisResult | None:
    if not _truthy_env("TASKRADAR_USE_OPENCODE"):
        if _truthy_env("TASKRADAR_REQUIRE_OPENCODE"):
            raise RuntimeError("opencode provider is required but disabled")
        return None

    command = os.getenv("TASKRADAR_OPENCODE_COMMAND", "opencode")
    if not _command_exists(command):
        if _truthy_env("TASKRADAR_REQUIRE_OPENCODE"):
            raise RuntimeError("opencode command not found")
        return None

    prompt = build_analysis_prompt(_messages_for_provider(messages), reference_date, senior_reply)
    prompt = "\n".join(
        [
            prompt,
            "",
            "최종 응답은 JSON 객체 하나만 출력하세요.",
            "JSON 앞뒤에 설명, 마크다운, 코드블록, 로그를 붙이지 마세요.",
        ]
    )
    data = _run_opencode_json(
        prompt,
        title="TaskRadar Analysis",
        instruction="첨부된 TaskRadar 분석 프롬프트를 처리하고 JSON 객체 하나만 출력하세요.",
    )
    return _result_from_provider_data(data, reference_date, "opencode-cli", senior_reply)


def _analyze_with_anthropic(messages: list[ChatMessage], reference_date: ReferenceTime, senior_reply: str) -> AnalysisResult | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    prompt = build_analysis_prompt(_messages_for_provider(messages), reference_date, senior_reply)
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
        },
        json={
            "model": os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
            "max_tokens": int(os.getenv("ANTHROPIC_MAX_TOKENS", "1800")),
            "temperature": 0.1,
            "system": "너는 카카오톡 업무 대화 분석기다. 반드시 유효한 JSON 객체만 출력한다.",
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=float(os.getenv("ANTHROPIC_TIMEOUT", "45")),
    )
    response.raise_for_status()
    payload = response.json()
    content = payload.get("content") or []
    text = "\n".join(part.get("text", "") for part in content if isinstance(part, dict)).strip()
    data = _load_json(text or "{}")
    return _result_from_provider_data(data, reference_date, "anthropic", senior_reply)


def _analyze_with_openai(messages: list[ChatMessage], reference_date: ReferenceTime, senior_reply: str) -> AnalysisResult | None:
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("openai 패키지가 설치되어 있지 않습니다.") from exc

    timeout = float(os.getenv("OPENAI_TIMEOUT", "45"))
    client = OpenAI(timeout=timeout)
    prompt = build_analysis_prompt(_messages_for_provider(messages), reference_date, senior_reply)
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    data = _load_json(content)
    return _result_from_provider_data(data, reference_date, "openai", senior_reply)


def _result_from_provider_data(
    data: dict[str, Any],
    reference_date: ReferenceTime,
    provider: str,
    senior_reply: str = "",
) -> AnalysisResult:
    reference_day = _reference_day(reference_date)
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
        score, level, risk_reasons = score_miss_risk(item.raw_text, item.due or item.datetime_start, reference_day)
        item.miss_risk_score = int(raw.get("miss_risk_score") or score)
        item.miss_risk_level = str(raw.get("miss_risk_level") or level)
        item.ambiguities = item.ambiguities or risk_reasons
        items.append(item)
    if senior_reply.strip():
        _apply_senior_reply(items, senior_reply, reference_day)
    attach_reminders(items)
    notification = build_morning_notification(items)
    return AnalysisResult(
        summary=str(data.get("summary") or _build_summary(items)),
        reference_date=reference_day,
        items=items,
        recommended_messages=list(data.get("recommended_messages") or _build_recommended_messages(items)),
        questions_to_senior=str(data.get("questions_to_senior") or _combine_questions(items)),
        morning_notification_preview=notification,
        senior_reply_update=_build_update_note(senior_reply) if senior_reply.strip() else "",
        provider=provider,
    )


def _fallback_analyze(messages: list[ChatMessage], reference_date: ReferenceTime, senior_reply: str = "") -> AnalysisResult:
    reference_day = _reference_day(reference_date)
    items: list[AnalysisItem] = []
    for message in messages:
        text = message.message.strip()
        if not _looks_actionable(text):
            continue
        item_type = _classify_type(text)
        target_dt, confidence = infer_datetime(text, reference_day)
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
        score, level, risk_reasons = score_miss_risk(text, item.due or item.datetime_start, reference_day)
        item.miss_risk_score = score
        item.miss_risk_level = level
        item.ambiguities = list(dict.fromkeys(item.ambiguities + risk_reasons))
        items.append(item)

    if senior_reply.strip():
        _apply_senior_reply(items, senior_reply, reference_day)

    attach_reminders(items)
    return AnalysisResult(
        summary=_build_summary(items),
        reference_date=reference_day,
        items=items,
        recommended_messages=_build_recommended_messages(items),
        questions_to_senior=_combine_questions(items),
        morning_notification_preview=build_morning_notification(items),
        senior_reply_update=_build_update_note(senior_reply) if senior_reply.strip() else "",
        provider="fallback",
    )


def _opencode_unavailable_result(reference_date: ReferenceTime, provider_errors: list[str]) -> AnalysisResult:
    reference_day = _reference_day(reference_date)
    return AnalysisResult(
        summary="AI 분석 연결을 확인해야 합니다.",
        reference_date=reference_day,
        items=[],
        recommended_messages=[],
        questions_to_senior="현재 AI 분석 연결이 원활하지 않아 결과를 만들 수 없습니다.",
        morning_notification_preview="AI 분석 연결을 확인한 뒤 다시 시도해 주세요.",
        provider="opencode-unavailable",
        provider_error="opencode 연결 실패로 분석을 완료하지 못했습니다.",
        warnings=provider_errors,
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
        return "발표자료는 기한 맞춰 준비하겠습니다. 제출 양식이나 올릴 위치가 정해져 있으면 알려주시면 그 기준으로 맞추겠습니다."
    if "아이디어" in item.title:
        return "AI Agent 아이디어는 3개 정도 정리해 보겠습니다. 문제, 해결 방법, 기대 효과 중심으로 정리하면 괜찮을까요?"
    if item.ambiguities:
        return f"{item.title} 관련해서 {item.ambiguities[0]} 부분만 한번 확인 부탁드립니다."
    return f"{item.title} 내용으로 이해했습니다. 추가로 맞춰야 할 기준이 있으면 알려주세요."


def _make_checklist(text: str) -> list[str]:
    checklist = ["요청받은 기한 확인", "완료 후 공유 대상 확인"]
    if "발표자료" in text or "자료" in text:
        checklist += ["파일명에 이름/날짜 포함", "분량과 양식 확인", "오탈자 확인", "제출 경로 확인"]
    if "아이디어" in text:
        checklist += ["아이디어 개수 확인", "문제/해결/효과 구조로 정리", "공유 형식 확인"]
    return list(dict.fromkeys(checklist))


def _apply_senior_reply(
    items: list[AnalysisItem],
    senior_reply: str,
    reference_date: ReferenceTime | None = None,
    target_item_ids: list[str] | None = None,
) -> None:
    details = _extract_senior_reply_details(senior_reply, reference_date)
    targets = _senior_reply_targets(items, senior_reply, details, target_item_ids)
    if not details or not targets:
        return

    for item in targets:
        if item.type not in ("일정", "할일", "확인필요"):
            continue

        item.resolved_details.update(details)
        if "기한" in details:
            if item.type == "일정":
                item.datetime_start = details["기한"]
                item.resolved_details["일시"] = details["기한"]
            else:
                item.due = details["기한"]
        if "날짜 확실도" in details:
            item.date_confidence = details["날짜 확실도"]

        item.ambiguities = _remaining_ambiguities(item.ambiguities, details)
        if item.classification == "확인필요":
            item.classification = "확정" if not item.ambiguities else "후보"
        item.checklist = _updated_checklist(item.checklist, details)
        item.suggested_question = _senior_reply_acknowledgement(item, details)


def _extract_senior_reply_details(senior_reply: str, reference_date: ReferenceTime | None) -> dict[str, str]:
    details: dict[str, str] = {}
    upper_reply = senior_reply.upper()

    if "PPT" in upper_reply:
        details["양식"] = "PPT"
    elif "워드" in senior_reply or "문서" in senior_reply:
        details["양식"] = "문서"
    elif "엑셀" in senior_reply or "스프레드시트" in senior_reply:
        details["양식"] = "스프레드시트"

    page_match = re.search(r"(\d+)\s*(?:장|페이지|쪽)", senior_reply)
    if page_match:
        details["분량"] = f"{page_match.group(1)}장 이내"

    if "팀즈" in senior_reply or "과제방" in senior_reply:
        details["제출 경로"] = "팀즈 과제방"
    elif "메일" in senior_reply or "이메일" in senior_reply:
        details["제출 경로"] = "메일"
    elif "드라이브" in senior_reply:
        details["제출 경로"] = "공유 드라이브"

    if reference_date and _looks_like_deadline_reply(senior_reply):
        reference_day = _reference_day(reference_date)
        target_dt, confidence = infer_datetime(senior_reply, reference_day)
        if target_dt:
            details["기한"] = target_dt
            details["날짜 확실도"] = confidence

    return details


def _looks_like_deadline_reply(text: str) -> bool:
    deadline_tokens = ("까지", "전까지", "마감", "기한", "오전", "오후", "시", "분", "오늘", "내일", "월요일", "화요일", "수요일", "목요일", "금요일")
    return any(token in text for token in deadline_tokens)


def _senior_reply_targets(
    items: list[AnalysisItem],
    senior_reply: str,
    details: dict[str, str],
    target_item_ids: list[str] | None = None,
) -> list[AnalysisItem]:
    actionable = [item for item in items if item.type in ("일정", "할일", "확인필요")]
    explicit_ids = set(target_item_ids or [])
    if explicit_ids:
        return [item for item in actionable if item.id in explicit_ids]

    matched = [
        item
        for item in actionable
        if _reply_mentions_item(item, senior_reply) or _reply_details_fit_item(item, details)
    ]
    if matched:
        return matched

    ambiguous = [item for item in actionable if item.ambiguities or item.classification == "확인필요"]
    if ambiguous:
        return ambiguous
    return matched or actionable


def _reply_mentions_item(item: AnalysisItem, senior_reply: str) -> bool:
    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", f"{item.title} {item.raw_text}"):
        if token not in seen:
            tokens.append(token)
            seen.add(token)
    generic = {
        "이번", "다음", "오늘", "내일", "오전", "오후", "까지", "정도",
        "해주세요", "부탁", "부탁드립니다", "정리", "공유", "제출",
        "작성", "준비", "확인", "관련", "이내", "발표",
    }
    meaningful = [token for token in tokens if token not in generic]
    return any(token in senior_reply for token in meaningful)


def _reply_details_fit_item(item: AnalysisItem, details: dict[str, str]) -> bool:
    context = _item_search_context(item)
    primary_context = _item_primary_context(item)
    if any(key in details for key in ("양식", "분량")):
        if any(token in primary_context for token in ("발표자료", "자료", "보고서", "문서", "파일", "양식", "분량", "PPT")):
            return True

    if "제출 경로" in details:
        if any(token in primary_context for token in ("제출", "업로드", "올려", "과제방", "발표자료", "자료", "보고서", "문서", "파일")):
            return True

    if "기한" in details:
        if any(token in context for token in ("기한", "마감", "까지", "전까지", "퇴근 전", "날짜", "시간", "오전", "오후")):
            return True

    return False


def _item_search_context(item: AnalysisItem) -> str:
    return " ".join(
        [
            item.title,
            item.raw_text,
            " ".join(item.ambiguities),
            " ".join(item.checklist),
        ]
    )


def _item_primary_context(item: AnalysisItem) -> str:
    return " ".join([item.title, item.raw_text, " ".join(item.checklist)])


def _remaining_ambiguities(ambiguities: list[str], details: dict[str, str]) -> list[str]:
    remaining: list[str] = []
    for ambiguity in ambiguities:
        if _detail_resolves_ambiguity(ambiguity, details):
            continue
        remaining.append(ambiguity)
    return remaining


def _detail_resolves_ambiguity(ambiguity: str, details: dict[str, str]) -> bool:
    if "기한" in details and any(token in ambiguity for token in ("시간", "날짜", "기한", "퇴근 전", "불명확", "미정")):
        return True
    if any(key in details for key in ("양식", "분량")) and any(token in ambiguity for token in ("형식", "양식", "분량", "후속 정보", "미확정")):
        return True
    if "제출 경로" in details and any(token in ambiguity for token in ("제출", "공유", "경로", "후속 정보", "미확정")):
        return True
    return False


def _updated_checklist(checklist: list[str], details: dict[str, str]) -> list[str]:
    added = [f"{key}: {_display_detail_value(key, value)}" for key, value in details.items() if key != "날짜 확실도"]
    return list(dict.fromkeys(checklist + added))


def _senior_reply_acknowledgement(item: AnalysisItem, details: dict[str, str]) -> str:
    summary = ", ".join(
        f"{key}은 {_display_detail_value(key, value)}"
        for key, value in details.items()
        if key != "날짜 확실도"
    )
    if not summary:
        return item.suggested_question
    if item.ambiguities:
        return f"확인 감사합니다. {item.title}은 {summary} 기준으로 진행하고, 남은 확인 사항만 추가로 맞춰보겠습니다."
    return f"확인 감사합니다. {item.title}은 {summary} 기준으로 진행하겠습니다."


def _display_detail_value(key: str, value: str) -> str:
    if key not in {"기한", "일시"}:
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    weekday = "월화수목금토일"[parsed.weekday()]
    return f"{parsed:%Y-%m-%d}({weekday}) {parsed:%H:%M}"


def _merge_update_patch(items: list[AnalysisItem], patch_data: dict[str, Any], allowed_ids: set[str]) -> None:
    by_id = {item.id: item for item in items}
    updates = patch_data.get("updates")
    if not isinstance(updates, list):
        raise RuntimeError("invalid patch response: updates missing")

    for update in updates:
        if not isinstance(update, dict):
            continue
        item_id = str(update.get("id") or "")
        if item_id not in allowed_ids or item_id not in by_id:
            continue
        _merge_item_update(by_id[item_id], update)


def _merge_item_update(item: AnalysisItem, update: dict[str, Any]) -> None:
    for field in ("due", "datetime_start"):
        if field in update:
            value = update.get(field)
            setattr(item, field, str(value) if value else None)

    for field in ("date_confidence", "classification", "importance", "suggested_question"):
        value = update.get(field)
        if isinstance(value, str) and value.strip():
            setattr(item, field, value.strip())

    ambiguities = update.get("ambiguities")
    if isinstance(ambiguities, list):
        item.ambiguities = [str(value).strip() for value in ambiguities if str(value).strip()]

    resolved_details = update.get("resolved_details")
    if isinstance(resolved_details, dict):
        item.resolved_details.update({str(key): str(value) for key, value in resolved_details.items() if value is not None})

    checklist = update.get("checklist")
    if isinstance(checklist, list):
        item.checklist = list(dict.fromkeys(str(value).strip() for value in checklist if str(value).strip()))

    checklist_add = update.get("checklist_add")
    if isinstance(checklist_add, list):
        additions = [str(value).strip() for value in checklist_add if str(value).strip()]
        item.checklist = list(dict.fromkeys(item.checklist + additions))


def _run_opencode_json(prompt: str, title: str, instruction: str) -> dict[str, Any]:
    if not _truthy_env("TASKRADAR_USE_OPENCODE"):
        if _truthy_env("TASKRADAR_REQUIRE_OPENCODE"):
            raise RuntimeError("opencode provider is required but disabled")
        raise RuntimeError("opencode provider is disabled")

    command = os.getenv("TASKRADAR_OPENCODE_COMMAND", "opencode")
    if not _command_exists(command):
        if _truthy_env("TASKRADAR_REQUIRE_OPENCODE"):
            raise RuntimeError("opencode command not found")
        raise RuntimeError("opencode command not found")

    model = os.getenv("TASKRADAR_OPENCODE_MODEL", "openai/gpt-5.4-mini")
    timeout = float(os.getenv("TASKRADAR_OPENCODE_TIMEOUT", "180"))
    temp_path = _write_opencode_prompt_file(prompt)
    try:
        args = [
            command,
            "run",
            "--title",
            title,
            "-m",
            model,
            instruction,
            "--file",
            str(temp_path),
        ]
        completed = subprocess.run(
            args,
            cwd=_opencode_work_dir(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    finally:
        _unlink_file_safely(temp_path)

    if completed.returncode != 0:
        raise RuntimeError(f"opencode exited with status {completed.returncode}")

    return _load_json(completed.stdout or "{}")


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
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _format_provider_error(provider_name: str, exc: Exception) -> str:
    label = provider_name.replace("_analyze_with_", "")
    return f"{label}: {type(exc).__name__}"


def _truthy_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _reference_day(reference_date: ReferenceTime) -> date:
    if isinstance(reference_date, datetime):
        return reference_date.date()
    return reference_date


def _command_exists(command: str) -> bool:
    if os.path.isabs(command) or os.sep in command:
        return Path(command).exists()
    return shutil.which(command) is not None


def _write_opencode_prompt_file(prompt: str) -> Path:
    temp_dir = Path(os.getenv("TASKRADAR_TEMP_DIR", tempfile.gettempdir())).resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".taskradar.txt",
        prefix="taskradar-",
        dir=temp_dir,
        delete=False,
    ) as handle:
        handle.write(prompt)
        return Path(handle.name).resolve()


def _opencode_work_dir() -> Path:
    work_dir = Path(
        os.getenv("TASKRADAR_OPENCODE_WORK_DIR")
        or (Path(tempfile.gettempdir()) / "taskradar-opencode-work")
    ).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    return work_dir


def _unlink_file_safely(path: Path) -> None:
    try:
        resolved = path.resolve()
        if resolved.name.startswith("taskradar-") and resolved.suffix == ".txt":
            resolved.unlink(missing_ok=True)
    except OSError:
        pass
