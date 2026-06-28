from __future__ import annotations

import html
import hmac
import copy
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from zoneinfo import ZoneInfo

import streamlit as st

from config import is_debug_mode, load_local_env
from models import AnalysisItem
from notification_provider import PreviewNotificationProvider
from task_extractor import analyze_text, update_result_with_senior_reply


SAMPLE_PATH = Path(__file__).with_name("sample_chat.txt")
MAX_UPLOAD_FILES = 3
KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


@dataclass(frozen=True)
class ChatSource:
    name: str
    text: str


def main() -> None:
    load_local_env()
    st.set_page_config(page_title="신입 업무 레이더 Agent", layout="wide", initial_sidebar_state="collapsed")
    _inject_styles()
    if not _pass_access_gate():
        return

    reference_at = datetime.now(KST).replace(second=0, microsecond=0)
    mode = _configured_mode()

    st.title("신입 업무 레이더 Agent")
    st.write("카카오톡 대화에서 To-Do, 확인 문구, 일정을 빠르게 정리합니다.")

    st.markdown(
        dedent(f"""
        <div class="tr-reference">
          <span>기준 시간</span>
          <strong>{html.escape(_format_reference_time(reference_at))}</strong>
        </div>
        """),
        unsafe_allow_html=True,
    )

    sources = _render_input_area(mode)
    raw_text = _combine_sources(sources)

    if st.button("분석하기", type="primary", use_container_width=True):
        if not raw_text.strip():
            st.warning("분석할 대화 내용을 업로드하거나 입력해 주세요.")
            return
        with st.spinner("대화에서 To-Do와 확인 필요사항을 찾는 중입니다..."):
            st.session_state["analysis_raw"] = raw_text
            st.session_state["analysis_ref"] = reference_at
            st.session_state["analysis_sources"] = sources
            st.session_state["senior_replies"] = []
            st.session_state.pop("selected_todo_id", None)
            st.session_state["analysis_result"] = _get_or_run_analysis(raw_text, reference_at)
            _clear_reply_target_selection()

    result = st.session_state.get("analysis_result")
    if not result:
        _render_empty_state(mode)
        return

    _render_result(result, mode, st.session_state.get("analysis_ref", reference_at))


def _configured_mode() -> str:
    mode = os.getenv("TASKRADAR_MODE", "local").strip().lower()
    return "demo" if mode == "demo" else "local"


def _pass_access_gate() -> bool:
    expected = os.getenv("TASKRADAR_ACCESS_PASSWORD", "").strip()
    if not expected:
        return True
    if st.session_state.get("access_granted") is True:
        return True

    st.title("TaskRadar")
    with st.form("access_gate"):
        password = st.text_input("접속 비밀번호", type="password")
        submitted = st.form_submit_button("입장", use_container_width=True)

    if submitted:
        if hmac.compare_digest(password, expected):
            st.session_state["access_granted"] = True
            st.rerun()
        else:
            st.error("비밀번호가 맞지 않습니다.")
    return False


def _render_input_area(mode: str) -> list[ChatSource]:
    sample_text = SAMPLE_PATH.read_text(encoding="utf-8") if SAMPLE_PATH.exists() else ""
    use_sample = st.toggle("샘플 대화 사용", value=mode == "demo")

    uploaded_files = st.file_uploader(
        "카카오톡 대화 내보내기 .txt 업로드",
        type=["txt"],
        accept_multiple_files=True,
        help="채팅방별 파일을 한 번에 올릴 수 있습니다. 최대 3개까지만 분석합니다.",
    )

    selected_files = list(uploaded_files or [])
    if len(selected_files) > MAX_UPLOAD_FILES:
        st.warning(f"파일은 최대 {MAX_UPLOAD_FILES}개까지만 처리합니다. 앞의 {MAX_UPLOAD_FILES}개 파일만 분석에 사용됩니다.")
        selected_files = selected_files[:MAX_UPLOAD_FILES]

    default_text = sample_text if use_sample and not selected_files else ""
    manual_text = st.text_area(
        "대화 내용 직접 입력",
        value=default_text,
        height=180,
        placeholder="[선배] 이번 주 금요일 오전 10시에 발표 리허설 있어요.\n[나] 네, 확인했습니다.",
    )

    sources: list[ChatSource] = []
    for index, uploaded in enumerate(selected_files, start=1):
        text = uploaded.getvalue().decode("utf-8-sig", errors="replace")
        if text.strip():
            sources.append(ChatSource(name=f"{index}. {uploaded.name}", text=text))

    if manual_text.strip():
        source_name = "샘플 대화" if use_sample and manual_text == sample_text else "직접 입력"
        sources.append(ChatSource(name=source_name, text=manual_text))

    if len(sources) > MAX_UPLOAD_FILES:
        st.warning(f"분석 입력은 최대 {MAX_UPLOAD_FILES}개 대화까지만 사용합니다. 초과 입력은 이번 분석에서 제외됩니다.")
        return sources[:MAX_UPLOAD_FILES]
    return sources


def _combine_sources(sources: list[ChatSource]) -> str:
    return "\n\n".join(source.text.strip() for source in sources if source.text.strip())


def _render_empty_state(mode: str) -> None:
    if mode == "demo":
        st.info("샘플 대화를 사용해 바로 분석 결과를 확인할 수 있습니다.")
    else:
        st.info("카카오톡 대화 내보내기 파일을 업로드하거나 대화 내용을 붙여넣고 분석을 시작하세요.")


def _render_result(result, mode: str, reference_at: datetime) -> None:
    if is_debug_mode():
        st.caption(f"분석 provider: {result.provider}")
    if result.provider_error:
        if result.provider == "opencode-unavailable":
            st.error("AI 분석 연결이 원활하지 않아 결과를 만들 수 없습니다. 잠시 후 다시 시도해 주세요.")
        else:
            st.warning("AI 분석 연결이 원활하지 않아 임시 분석 결과를 표시했습니다. 잠시 후 다시 시도해 주세요.")
    if is_debug_mode():
        for warning in result.warnings:
            st.caption(f"provider 경고: {warning}")

    st.divider()
    st.subheader("To-Do")
    if result.senior_reply_update:
        st.success(result.senior_reply_update)
    st.markdown('<span id="todo-section"></span>', unsafe_allow_html=True)
    _render_todo_workspace(result.items)

    st.divider()
    st.subheader("선배 답변 재입력")
    st.write("답변을 적용할 To-Do를 먼저 선택한 뒤, 선배에게 받은 답변을 붙여넣으세요.")
    _render_senior_reply_history()
    selected_reply_targets = _render_reply_target_selector(result.items)
    with st.form("senior_reply_form", clear_on_submit=True):
        senior_reply = st.text_area(
            "선배 답변",
            height=100,
            placeholder="예: 양식은 PPT 5장 이내고, 팀즈 과제방에 올려주세요.",
        )
        submitted = st.form_submit_button("답변 반영하기", use_container_width=True)
    if submitted:
        new_reply = senior_reply.strip()
        if not new_reply:
            st.warning("반영할 선배 답변을 입력해 주세요.")
            return
        if not selected_reply_targets:
            st.warning("답변을 반영할 To-Do를 하나 이상 선택해 주세요.")
            return
        raw = st.session_state.get("analysis_raw", "")
        ref = st.session_state.get("analysis_ref", reference_at)
        history = list(st.session_state.get("senior_replies", []))
        history.append(new_reply)
        st.session_state["senior_replies"] = history
        with st.spinner("선배 답변을 To-Do에 반영하는 중입니다..."):
            current_result = st.session_state.get("analysis_result")
            if current_result:
                st.session_state["analysis_result"] = update_result_with_senior_reply(
                    current_result,
                    new_reply,
                    target_item_ids=selected_reply_targets,
                )
            else:
                st.session_state["analysis_result"] = _get_or_run_analysis(raw, ref, senior_reply=new_reply)
        _clear_reply_target_selection()
        st.rerun()

    st.subheader("카카오톡 알림 보내기")
    st.write(
        "현재 데모에서는 실제 카카오톡 메시지를 보내지 않고, 매일 오전 8시에 받을 알림 문구를 미리 보여줍니다. "
        "이후 카카오 OAuth와 나에게 보내기 API를 연결하면 같은 내용을 실제 알림으로 전송할 수 있습니다."
    )
    _render_notification_preview(result, mode)


def _render_todo_workspace(items: list[AnalysisItem]) -> None:
    if not items:
        st.info("정리할 To-Do가 발견되지 않았습니다.")
        return

    selected_id = _selected_todo_id(items)
    st.caption("카드 섹션을 클릭하면 해당 To-Do의 체크리스트와 선배에게 보낼 문구가 오른쪽에 표시됩니다.")

    st.session_state["selected_todo_id"] = selected_id

    for item in items:
        selected = item.id == selected_id
        card_col, detail_col = st.columns([0.48, 0.52], gap="large")
        with card_col:
            if _render_todo_card_button(item, selected=selected):
                st.session_state["selected_todo_id"] = item.id
                st.rerun()
        with detail_col:
            if selected:
                st.markdown(_todo_detail_html(item), unsafe_allow_html=True)


def _render_todo_card_button(item: AnalysisItem, selected: bool) -> bool:
    due = _format_due(item)
    verification_note = _format_verification_summary(item)
    label = (
        f"{item.type} · 우선순위 {item.importance}\n\n"
        f"{item.title}\n\n"
        f"기한/일시\n\n"
        f"{due}\n\n"
        f"확인해 볼 사항\n\n"
        f"{verification_note}"
    )
    return st.button(
        label,
        key=f"todo-card-{item.id}",
        use_container_width=True,
        type="primary" if selected else "secondary",
    )


def _render_reply_target_selector(items: list[AnalysisItem]) -> list[str]:
    actionable = [item for item in items if item.type in ("일정", "할일", "확인필요")]
    if not actionable:
        st.info("답변을 반영할 To-Do가 없습니다.")
        return []

    st.markdown("##### 답변을 반영할 To-Do 선택")
    st.caption("여러 개를 선택할 수 있습니다. 선택한 카드는 연두색으로 표시됩니다.")

    selected_ids: list[str] = []
    columns = st.columns(3)
    for index, item in enumerate(actionable):
        with columns[index % 3]:
            selected = st.checkbox(
                f"**{item.title}**\n\n{item.type} · {_format_due(item)}",
                key=f"reply-target-{item.id}",
            )
            if selected:
                selected_ids.append(item.id)
    return selected_ids


def _clear_reply_target_selection() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith("reply-target-"):
            st.session_state.pop(key, None)


def _todo_detail_html(item: AnalysisItem) -> str:
    message = item.suggested_question or _fallback_message_for_item(item)
    checklist = "\n".join(
        f"<li>☐ {html.escape(check)}</li>"
        for check in _checklist_for_item(item)
    )
    return dedent(f"""
    <div class="tr-todo-detail-card">
      <div class="tr-detail-eyebrow">선택한 To-Do</div>
      <h3>{html.escape(item.title)}</h3>
      <div class="tr-detail-meta">
        <span>{html.escape(item.type)}</span>
        <span>{html.escape(_format_due(item))}</span>
      </div>
      <div class="tr-detail-block">
        <strong>확인해 볼 사항</strong>
        <p>{html.escape(_format_verification_detail(item))}</p>
      </div>
      <div class="tr-detail-block message">
        <strong>추천 문구</strong>
        <p>{html.escape(message)}</p>
      </div>
      <div class="tr-detail-checklist">
        <strong>체크리스트</strong>
        <ul>{checklist}</ul>
      </div>
    </div>
    """).strip()


def _render_todo_detail(item: AnalysisItem) -> None:
    message = item.suggested_question or _fallback_message_for_item(item)
    st.markdown(
        dedent(f"""
        <div class="tr-detail-card">
          <div class="tr-detail-eyebrow">선택한 To-Do</div>
          <h3>{html.escape(item.title)}</h3>
          <div class="tr-detail-meta">
            <span>{html.escape(item.type)}</span>
            <span>{html.escape(_format_due(item))}</span>
          </div>
          <div class="tr-detail-block">
            <strong>확인해 볼 사항</strong>
            <p>{html.escape(_format_verification_detail(item))}</p>
          </div>
          <div class="tr-detail-block message">
            <strong>추천 문구</strong>
            <p>{html.escape(message)}</p>
          </div>
        </div>
        """),
        unsafe_allow_html=True,
    )

    st.markdown("#### 체크리스트")
    for checklist in _checklist_for_item(item):
        st.checkbox(checklist, key=f"detail-check-{item.id}-{checklist}")


def _render_work_requests(items: list[AnalysisItem]) -> None:
    if not items:
        st.info("업무 요청이 발견되지 않았습니다.")
        return

    for item in items:
        due = _format_due(item)
        ambiguity = _format_verification_summary(item)
        type_class = "schedule" if item.type == "일정" else "verify" if item.type == "확인필요" else "todo"
        importance_class = _importance_class(item.importance)
        st.markdown(
            dedent(f"""
            <div class="tr-work-card {type_class}">
              <div class="tr-work-top">
                <span class="tr-pill {type_class}">{html.escape(item.type)}</span>
                <span class="tr-priority {importance_class}">우선순위 {html.escape(item.importance)}</span>
              </div>
              <div class="tr-work-title">{html.escape(item.title)}</div>
              <div class="tr-work-grid">
                <div><span>기한/일시</span><strong>{html.escape(due)}</strong></div>
                <div><span>확인해 볼 사항</span><strong>{html.escape(ambiguity)}</strong></div>
              </div>
            </div>
            """),
            unsafe_allow_html=True,
        )


def _render_recommended_messages(result) -> None:
    messages = result.recommended_messages or [result.questions_to_senior]
    messages = [message.strip() for message in messages if message and message.strip()]
    if not messages:
        st.info("현재 선배에게 추가로 확인할 문구가 없습니다.")
        return

    for index, message in enumerate(messages, start=1):
        st.markdown(
            dedent(f"""
            <div class="tr-message-card">
              <div class="tr-message-label">문구 {index}</div>
              <div>{html.escape(message)}</div>
            </div>
            """),
            unsafe_allow_html=True,
        )


def _render_todo_schedule(items: list[AnalysisItem]) -> None:
    todo_items = [item for item in items if item.type != "일정"]
    schedule_items = [item for item in items if item.type == "일정"]

    left, right = st.columns(2)
    with left:
        st.markdown("#### To-Do")
        if not todo_items:
            st.caption("데이터 없음")
        for item in todo_items:
            due = _format_due(item)
            st.checkbox(f"{item.title} · {due}", key=f"todo-{item.id}")
            if item.checklist:
                st.caption(" / ".join(item.checklist[:4]))

    with right:
        st.markdown("#### 일정")
        if not schedule_items:
            st.caption("데이터 없음")
        for item in schedule_items:
            st.markdown(
                dedent(f"""
                <div class="tr-schedule-row">
                  <strong>{html.escape(item.title)}</strong>
                  <span>{html.escape(_format_due(item))}</span>
                </div>
                """),
                unsafe_allow_html=True,
            )


def _render_notification_preview(result, mode: str) -> None:
    provider = PreviewNotificationProvider()
    preview = provider.build_preview(result.morning_notification_preview)
    st.markdown(
        dedent(f"""
        <div class="tr-notification">
          <div class="tr-notification-head">
            <span>{html.escape(preview.channel)}</span>
            <strong>{html.escape(preview.send_time)}</strong>
          </div>
          <pre>{html.escape(preview.message)}</pre>
        </div>
        """),
        unsafe_allow_html=True,
    )
    if mode == "demo":
        st.caption("웹 데모에서는 실제 카카오톡 발송을 하지 않습니다.")


def _format_reference_time(reference_at: datetime) -> str:
    weekday = WEEKDAYS[reference_at.weekday()]
    return f"{reference_at:%Y-%m-%d} ({weekday}) {reference_at:%H:%M}"


def _format_due(item: AnalysisItem) -> str:
    target = item.due or item.datetime_start
    if not target:
        return "확인 필요"
    try:
        parsed = datetime.fromisoformat(target)
    except ValueError:
        return target
    weekday = WEEKDAYS[parsed.weekday()]
    return f"{parsed:%Y-%m-%d} ({weekday}) {parsed:%H:%M}"


def _selected_todo_id(items: list[AnalysisItem]) -> str:
    item_ids = {item.id for item in items}
    session_selected = st.session_state.get("selected_todo_id")
    if session_selected in item_ids:
        return str(session_selected)
    return items[0].id


def _render_senior_reply_history() -> None:
    history = [reply for reply in st.session_state.get("senior_replies", []) if reply.strip()]
    if not history:
        return
    rows = "\n".join(
        f"<li><strong>{index}차 답변</strong><span>{html.escape(reply)}</span></li>"
        for index, reply in enumerate(history, start=1)
    )
    st.markdown(
        dedent(f"""
        <div class="tr-reply-history">
          <div>이미 반영한 답변</div>
          <ul>{rows}</ul>
        </div>
        """),
        unsafe_allow_html=True,
    )


def _combine_senior_replies(replies: list[str]) -> str:
    return "\n".join(f"{index}차 답변: {reply.strip()}" for index, reply in enumerate(replies, start=1) if reply.strip())


def _get_or_run_analysis(raw_text: str, reference_at: datetime, senior_reply: str = ""):
    cache = st.session_state.setdefault("analysis_cache", {})
    key = _analysis_cache_key(raw_text, reference_at, senior_reply)
    if key in cache:
        return copy.deepcopy(cache[key])

    result = analyze_text(raw_text, reference_at, senior_reply=senior_reply)
    cache[key] = copy.deepcopy(result)
    return result


def _analysis_cache_key(raw_text: str, reference_at: datetime, senior_reply: str = "") -> str:
    digest = hashlib.sha256()
    digest.update(raw_text.encode("utf-8", errors="ignore"))
    digest.update(b"\0")
    digest.update(reference_at.isoformat(timespec="minutes").encode("utf-8"))
    digest.update(b"\0")
    digest.update(senior_reply.encode("utf-8", errors="ignore"))
    digest.update(b"\0taskradar-analysis-v2")
    return digest.hexdigest()


def _format_verification_summary(item: AnalysisItem) -> str:
    if item.resolved_details:
        resolved = _resolved_detail_summary(item, limit=28)
        if not item.ambiguities:
            return f"반영됨: {resolved}"
        return f"일부 반영: {resolved}"

    if not item.ambiguities:
        return "추가 확인 낮음"

    labels = []
    for ambiguity in item.ambiguities:
        label = _ambiguity_to_short_label(ambiguity)
        if label not in labels:
            labels.append(label)
        if len(labels) == 2:
            break
    return " / ".join(labels)


def _format_verification_detail(item: AnalysisItem) -> str:
    if item.resolved_details:
        resolved = _resolved_detail_sentence(item)
        if not item.ambiguities:
            return f"선배 답변 기준으로 {resolved} 반영했습니다."

        intents = []
        for ambiguity in item.ambiguities[:2]:
            intent = _ambiguity_to_intent(ambiguity)
            if intent not in intents:
                intents.append(intent)
        intent_text = intents[0] if len(intents) == 1 else f"{intents[0]}와 {intents[1]}"
        return f"선배 답변 기준으로 {resolved} 반영했습니다. 다만 {intent_text}는 한 번 더 확인하면 좋습니다."

    if not item.ambiguities:
        return "현재 대화 기준으로 큰 확인 사항은 없습니다. 다만 준비물이나 공유 방식이 따로 있으면 추가 확인하면 좋습니다."

    raw_text = _shorten(item.raw_text or item.title, 54)
    intents = []
    for ambiguity in item.ambiguities[:2]:
        intent = _ambiguity_to_intent(ambiguity)
        if intent not in intents:
            intents.append(intent)

    if len(intents) == 1:
        intent_text = intents[0]
    else:
        intent_text = f"{intents[0]}와 {intents[1]}"
    return f"“{raw_text}”라고 하셨는데, {intent_text} 확인하면 좋습니다."


def _resolved_detail_summary(item: AnalysisItem, limit: int = 36) -> str:
    summary = ", ".join(value for _, value in _resolved_detail_pairs(item))
    return _shorten(summary or "답변 내용", limit)


def _resolved_detail_sentence(item: AnalysisItem) -> str:
    pairs = _resolved_detail_pairs(item)
    if not pairs:
        return "답변 내용을"
    parts = [f"{key}은 {value}" for key, value in pairs]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + f", {parts[-1]}"


def _resolved_detail_pairs(item: AnalysisItem) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key in ("기한", "일시", "양식", "분량", "제출 경로"):
        value = item.resolved_details.get(key)
        if not value:
            continue
        pairs.append((key, _format_resolved_value(key, value)))
    hidden_keys = {"기한", "일시", "양식", "분량", "제출 경로", "날짜 확실도"}
    for key, value in item.resolved_details.items():
        if key not in hidden_keys and value:
            pairs.append((key, _format_resolved_value(key, value)))
    return pairs


def _format_resolved_value(key: str, value: str) -> str:
    if key not in {"기한", "일시"}:
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    weekday = WEEKDAYS[parsed.weekday()]
    return f"{parsed:%Y-%m-%d} ({weekday}) {parsed:%H:%M}"


def _ambiguity_to_short_label(ambiguity: str) -> str:
    if "시간" in ambiguity or "퇴근 전" in ambiguity:
        return "마감 시간 확인"
    if "날짜" in ambiguity or "기한" in ambiguity:
        return "날짜 기준 확인"
    if "필수" in ambiguity or "우선순위" in ambiguity:
        return "우선순위 확인"
    if "형식" in ambiguity or "양식" in ambiguity or "분량" in ambiguity:
        return "양식/분량 확인"
    if "제출" in ambiguity or "공유" in ambiguity or "경로" in ambiguity:
        return "공유 경로 확인"
    if "후속" in ambiguity or "추후" in ambiguity:
        return "추후 정보 확인"
    return _shorten(ambiguity, 16)


def _ambiguity_to_intent(ambiguity: str) -> str:
    if "시간" in ambiguity or "퇴근 전" in ambiguity:
        return "정확히 몇 시까지를 의미하신 건지"
    if "날짜" in ambiguity or "기한" in ambiguity:
        return "정확한 날짜나 마감 기준을 어떤 의미로 보신 건지"
    if "필수" in ambiguity or "우선순위" in ambiguity:
        return "반드시 해야 하는 업무인지, 우선순위를 조정해도 되는지"
    if "형식" in ambiguity or "양식" in ambiguity or "분량" in ambiguity:
        return "어떤 양식과 분량으로 정리하라는 의도인지"
    if "제출" in ambiguity or "공유" in ambiguity or "경로" in ambiguity:
        return "어디로 제출하거나 공유하라는 의도인지"
    if "후속" in ambiguity or "추후" in ambiguity:
        return "추가 공유를 기다린 뒤 진행하라는 의도인지"
    return f"{ambiguity} 부분이 어떤 의도인지"


def _fallback_message_for_item(item: AnalysisItem) -> str:
    if item.ambiguities:
        return f"{item.title} 관련해서 {_ambiguity_to_intent(item.ambiguities[0])} 확인 부탁드립니다. 알려주시면 그 기준으로 진행하겠습니다."
    return f"{item.title}은 현재 내용 기준으로 진행하겠습니다. 추가로 맞춰야 할 기준이 있으면 알려주세요."


def _checklist_for_item(item: AnalysisItem) -> list[str]:
    if item.checklist:
        return item.checklist
    if item.type == "일정":
        return ["일정 시간 확인", "캘린더 등록", "필요 자료 사전 준비", "참석 전 최종 확인"]
    return ["기한 확인", "산출물 기준 확인", "공유/제출 경로 확인", "완료 후 선배에게 공유"]


def _shorten(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def _importance_class(importance: str) -> str:
    if importance == "높음":
        return "high"
    if importance == "낮음":
        return "low"
    return "medium"


def _is_mine(sender: str) -> bool:
    normalized = sender.strip().lower()
    return normalized in {"나", "저", "me", "i", "사용자"}


def _public_result_dict(result) -> dict:
    data = result.to_dict()
    if not is_debug_mode():
        data.pop("warnings", None)
        data.pop("provider_error", None)
        data.pop("provider", None)
    return data


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"],
        div[data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }
        .tr-reference {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            align-items: center;
            padding: 14px 18px;
            margin: 14px 0 22px;
            border: 1px solid #E5E7EB;
            border-radius: 14px;
            background: #F8FAFC;
        }
        .tr-reference span {
            color: #64748B;
            font-size: 13px;
            font-weight: 700;
        }
        .tr-reference strong {
            color: #0F172A;
            font-size: 16px;
        }
        .tr-chat-panel {
            max-height: 360px;
            overflow: auto;
            padding: 18px;
            border: 1px solid #E5E7EB;
            border-radius: 18px;
            background: linear-gradient(180deg, #F8FAFC 0%, #EEF6FF 100%);
            margin-bottom: 18px;
        }
        .tr-chat-row {
            margin-bottom: 12px;
            max-width: 76%;
        }
        .tr-chat-row.mine {
            margin-left: auto;
            text-align: right;
        }
        .tr-chat-meta {
            margin-bottom: 4px;
            color: #64748B;
            font-size: 12px;
        }
        .tr-chat-bubble {
            display: inline-block;
            padding: 10px 12px;
            border-radius: 14px;
            background: #FFFFFF;
            color: #111827;
            text-align: left;
            line-height: 1.55;
            box-shadow: 0 6px 18px rgba(15, 23, 42, .08);
        }
        .tr-chat-row.mine .tr-chat-bubble {
            background: #DBEAFE;
        }
        .tr-chat-note {
            color: #64748B;
            font-size: 12px;
            text-align: center;
            padding-top: 6px;
        }
        .tr-todo-grid {
            display: grid;
            grid-template-columns: minmax(0, .92fr) minmax(320px, 1.08fr);
            gap: 14px 24px;
            align-items: start;
        }
        .tr-todo-card {
            grid-column: 1;
            display: block;
            min-height: 156px;
            padding: 18px 20px 16px 20px;
            border: 1px solid #E5E7EB;
            border-left: 5px solid #CBD5E1;
            border-radius: 16px;
            background: #FFFFFF;
            color: #111827;
            text-decoration: none !important;
            box-shadow: 0 12px 30px rgba(15, 23, 42, .06);
            transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease, background .14s ease;
        }
        .tr-todo-card:hover {
            transform: translateY(-1px);
            border-color: #C7D2FE;
            border-left-color: #4F46E5;
            background: #F8FAFF;
            color: #111827;
            box-shadow: 0 16px 34px rgba(15, 23, 42, .10);
        }
        .tr-todo-card.todo { border-left-color: #2563EB; }
        .tr-todo-card.schedule { border-left-color: #059669; }
        .tr-todo-card.verify { border-left-color: #F59E0B; }
        .tr-todo-card.selected {
            border-color: #93C5FD;
            border-left-color: #2563EB;
            background: #EFF6FF;
            box-shadow: 0 16px 36px rgba(37, 99, 235, .14);
        }
        .tr-todo-card-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            margin-bottom: 10px;
        }
        .tr-todo-card-title {
            color: #0F172A;
            font-size: 20px;
            font-weight: 900;
            line-height: 1.25;
            margin-bottom: 14px;
        }
        .tr-todo-card-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 8px;
        }
        .tr-todo-card-grid div {
            padding: 10px 12px;
            border-radius: 12px;
            background: #F8FAFC;
        }
        .tr-todo-card.selected .tr-todo-card-grid div {
            background: rgba(255, 255, 255, .72);
        }
        .tr-todo-card-grid span {
            display: block;
            margin-bottom: 3px;
            color: #64748B;
            font-size: 12px;
            font-weight: 750;
        }
        .tr-todo-card-grid strong {
            color: #111827;
            font-size: 13px;
            line-height: 1.45;
        }
        .tr-todo-detail-card {
            grid-column: 2;
            max-height: 430px;
            overflow-y: auto;
            overflow-x: hidden;
            padding: 18px;
            border: 1px solid #BFDBFE;
            border-radius: 18px;
            background: linear-gradient(180deg, #FFFFFF 0%, #F8FBFF 100%);
            box-shadow: 0 16px 36px rgba(37, 99, 235, .12);
            scrollbar-width: auto;
            scrollbar-color: #93C5FD #EFF6FF;
        }
        .tr-todo-detail-card::-webkit-scrollbar {
            width: 12px;
        }
        .tr-todo-detail-card::-webkit-scrollbar-track {
            background: #EFF6FF;
            border-radius: 999px;
        }
        .tr-todo-detail-card::-webkit-scrollbar-thumb {
            background: #93C5FD;
            border: 3px solid #EFF6FF;
            border-radius: 999px;
        }
        .tr-todo-detail-card::-webkit-scrollbar-thumb:hover {
            background: #60A5FA;
        }
        .tr-todo-detail-card h3 {
            margin: 3px 0 10px;
            color: #0F172A;
            font-size: 19px;
            line-height: 1.28;
        }
        .tr-detail-checklist {
            margin-top: 12px;
            padding: 12px;
            border-radius: 12px;
            background: #F8FAFC;
        }
        .tr-detail-checklist strong {
            display: block;
            margin-bottom: 8px;
            color: #0F172A;
            font-size: 13px;
        }
        .tr-detail-checklist ul {
            margin: 0;
            padding: 0;
            list-style: none;
            color: #334155;
            font-size: 13px;
            line-height: 1.6;
        }
        .tr-reply-history {
            margin: 10px 0 14px;
            padding: 14px 16px;
            border: 1px solid #E5E7EB;
            border-radius: 14px;
            background: #F8FAFC;
        }
        .tr-reply-history > div {
            margin-bottom: 8px;
            color: #334155;
            font-size: 13px;
            font-weight: 800;
        }
        .tr-reply-history ul {
            margin: 0;
            padding: 0;
            list-style: none;
        }
        .tr-reply-history li {
            display: grid;
            grid-template-columns: 82px minmax(0, 1fr);
            gap: 10px;
            padding: 6px 0;
            border-top: 1px solid #E5E7EB;
            color: #334155;
            font-size: 13px;
            line-height: 1.5;
        }
        .tr-reply-history li:first-child {
            border-top: 0;
            padding-top: 0;
        }
        div[data-testid="stCheckbox"] {
            min-height: 88px;
            margin-bottom: 10px;
            padding: 12px 13px;
            border: 1px solid #E5E7EB;
            border-radius: 15px;
            background: #F8FAFC;
            box-shadow: 0 8px 18px rgba(15, 23, 42, .05);
            transition: border-color .15s ease, background .15s ease, box-shadow .15s ease, transform .15s ease;
        }
        div[data-testid="stCheckbox"]:hover {
            border-color: #BBF7D0;
            background: #F0FDF4;
            transform: translateY(-1px);
        }
        div[data-testid="stCheckbox"]:has(input:checked) {
            border-color: #86EFAC;
            background: #DCFCE7;
            box-shadow: 0 12px 24px rgba(22, 163, 74, .12);
        }
        div[data-testid="stCheckbox"] label {
            width: 100%;
            align-items: flex-start;
        }
        div[data-testid="stCheckbox"] p {
            color: #334155;
            font-size: 13px;
            line-height: 1.45;
        }
        div[data-testid="stCheckbox"]:has(input:checked) p {
            color: #14532D;
            font-weight: 720;
        }
        div.stButton > button {
            height: auto;
            white-space: pre-wrap;
        }
        div.stButton > button p {
            white-space: pre-wrap;
            line-height: 1.45;
        }
        div.stButton > button:has(p:nth-of-type(4)) {
            display: block;
            min-height: 156px;
            text-align: left;
            padding: 18px 20px;
            border: 1px solid #E5E7EB;
            border-left: 5px solid #CBD5E1;
            border-radius: 16px;
            background: #FFFFFF;
            color: #111827;
            box-shadow: 0 12px 30px rgba(15, 23, 42, .06);
            margin-bottom: 14px;
            transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease, background .14s ease;
        }
        div.stButton > button:has(p:nth-of-type(4)) > div {
            width: 100%;
        }
        div.stButton > button:has(p:nth-of-type(4)) [data-testid="stMarkdownContainer"] {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(190px, .86fr);
            grid-template-rows: auto auto auto auto;
            column-gap: 18px;
            row-gap: 4px;
            align-items: center;
            width: 100%;
        }
        div.stButton > button:has(p:nth-of-type(4)):hover {
            transform: translateY(-1px);
            border-color: #C7D2FE;
            border-left-color: #4F46E5;
            color: #111827;
            background: #F8FAFF;
            box-shadow: 0 16px 34px rgba(15, 23, 42, .10);
        }
        div.stButton > button:has(p:nth-of-type(4))[kind="primary"] {
            border-color: #93C5FD;
            border-left-color: #2563EB;
            background: #EFF6FF;
            color: #111827;
            box-shadow: 0 16px 36px rgba(37, 99, 235, .14);
        }
        div.stButton > button:has(p:nth-of-type(4)) p {
            width: 100%;
            min-width: 0;
            margin: 0;
            text-align: left;
        }
        div.stButton > button:has(p:nth-of-type(4)) p:first-child {
            grid-column: 1;
            grid-row: 1;
            align-self: end;
            color: #64748B;
            font-size: 12px;
            font-weight: 800;
        }
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(2) {
            grid-column: 1;
            grid-row: 2 / span 3;
            align-self: start;
            color: #0F172A;
            font-size: 20px;
            font-weight: 900;
            line-height: 1.25;
        }
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(3),
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(5) {
            grid-column: 2;
            color: #64748B;
            font-size: 11px;
            font-weight: 850;
            letter-spacing: 0;
            line-height: 1.25;
        }
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(3) {
            grid-row: 1;
            align-self: end;
        }
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(5) {
            grid-row: 3;
            align-self: end;
            margin-top: 8px;
        }
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(4),
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(6) {
            grid-column: 2;
            color: #475569;
            font-size: 13px;
            font-weight: 800;
            line-height: 1.35;
        }
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(4) {
            grid-row: 2;
            color: #0F172A;
        }
        div.stButton > button:has(p:nth-of-type(4)) p:nth-child(6) {
            grid-row: 4;
        }
        div.stButton > button:has(p:nth-of-type(4))[kind="primary"] p:first-child {
            color: #1D4ED8;
        }
        div.stButton > button:has(p:nth-of-type(4))[kind="primary"] p:nth-child(2) {
            color: #0B1F44;
        }
        .tr-detail-offset {
            pointer-events: none;
        }
        .tr-card-link {
            display: block;
            color: inherit;
            text-decoration: none !important;
            cursor: pointer;
        }
        .tr-card-link:focus-visible .tr-work-card {
            outline: 3px solid rgba(37, 99, 235, .35);
            outline-offset: 2px;
        }
        .tr-work-card {
            padding: 18px;
            border: 1px solid #E5E7EB;
            border-left-width: 5px;
            border-radius: 16px;
            background: #FFFFFF;
            box-shadow: 0 12px 30px rgba(15, 23, 42, .06);
            margin-bottom: 14px;
            transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease, background .14s ease;
        }
        .tr-card-link:hover .tr-work-card {
            transform: translateY(-1px);
            border-color: #BFDBFE;
            box-shadow: 0 16px 34px rgba(15, 23, 42, .10);
        }
        .tr-work-card.todo { border-left-color: #2563EB; }
        .tr-work-card.schedule { border-left-color: #059669; }
        .tr-work-card.verify { border-left-color: #F59E0B; }
        .tr-work-card.selected {
            border-color: #BFDBFE;
            border-left-color: #2563EB;
            background: #F8FBFF;
            box-shadow: 0 16px 36px rgba(37, 99, 235, .14);
        }
        .tr-work-top {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            align-items: center;
            margin-bottom: 10px;
        }
        .tr-pill, .tr-priority {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 4px 9px;
            font-size: 12px;
            font-weight: 800;
        }
        .tr-pill.todo { background: #DBEAFE; color: #1D4ED8; }
        .tr-pill.schedule { background: #D1FAE5; color: #047857; }
        .tr-pill.verify { background: #FEF3C7; color: #B45309; }
        .tr-priority.high { background: #FEE2E2; color: #DC2626; }
        .tr-priority.medium { background: #FFEDD5; color: #C2410C; }
        .tr-priority.low { background: #E0F2FE; color: #0369A1; }
        .tr-work-title {
            color: #0F172A;
            font-size: 18px;
            font-weight: 850;
            margin-bottom: 12px;
        }
        .tr-work-grid {
            display: grid;
            grid-template-columns: minmax(180px, .7fr) minmax(240px, 1.3fr);
            gap: 12px;
        }
        .tr-work-grid div {
            padding: 12px;
            border-radius: 12px;
            background: #F8FAFC;
        }
        .tr-work-grid span {
            display: block;
            margin-bottom: 4px;
            color: #64748B;
            font-size: 12px;
            font-weight: 700;
        }
        .tr-work-grid strong {
            color: #111827;
            font-size: 14px;
            line-height: 1.45;
        }
        .tr-card-footer {
            display: flex;
            justify-content: flex-end;
            margin-top: 12px;
        }
        .tr-click-hint, .tr-selected-badge {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 4px 9px;
            font-size: 12px;
            font-weight: 800;
        }
        .tr-click-hint {
            background: #F1F5F9;
            color: #64748B;
        }
        .tr-selected-badge {
            background: #DBEAFE;
            color: #1D4ED8;
        }
        .tr-message-card {
            padding: 16px;
            border: 1px solid #DBEAFE;
            border-radius: 16px;
            background: #F8FBFF;
            color: #111827;
            line-height: 1.65;
            margin-bottom: 12px;
        }
        .tr-message-label {
            color: #2563EB;
            font-size: 12px;
            font-weight: 850;
            margin-bottom: 6px;
        }
        .tr-detail-card {
            padding: 22px;
            border: 1px solid #DBEAFE;
            border-radius: 18px;
            background: linear-gradient(180deg, #FFFFFF 0%, #F8FBFF 100%);
            box-shadow: 0 16px 40px rgba(15, 23, 42, .08);
            margin-bottom: 16px;
        }
        .tr-detail-eyebrow {
            color: #2563EB;
            font-size: 12px;
            font-weight: 900;
            margin-bottom: 8px;
        }
        .tr-detail-card h3 {
            margin: 0 0 12px;
            color: #0F172A;
            font-size: 22px;
            line-height: 1.35;
        }
        .tr-detail-meta {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 16px;
        }
        .tr-detail-meta span {
            border-radius: 999px;
            padding: 5px 9px;
            background: #EFF6FF;
            color: #1D4ED8;
            font-size: 12px;
            font-weight: 800;
        }
        .tr-detail-block {
            padding: 14px;
            border-radius: 14px;
            background: #F8FAFC;
            margin-top: 12px;
        }
        .tr-detail-block.message {
            background: #ECFDF5;
            border: 1px solid #A7F3D0;
        }
        .tr-detail-block strong {
            display: block;
            margin-bottom: 6px;
            color: #334155;
            font-size: 13px;
        }
        .tr-detail-block p {
            margin: 0;
            color: #111827;
            line-height: 1.65;
        }
        .tr-schedule-row {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: center;
            padding: 12px 14px;
            border: 1px solid #E5E7EB;
            border-radius: 12px;
            background: #FFFFFF;
            margin-bottom: 10px;
        }
        .tr-schedule-row span {
            color: #2563EB;
            font-weight: 800;
            white-space: nowrap;
        }
        .tr-notification {
            max-width: 520px;
            padding: 18px;
            border-radius: 22px;
            background: #111827;
            color: #FFFFFF;
            box-shadow: 0 18px 40px rgba(17, 24, 39, .22);
        }
        .tr-notification-head {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            color: #CBD5E1;
            font-size: 13px;
            margin-bottom: 12px;
        }
        .tr-notification pre {
            white-space: pre-wrap;
            margin: 0;
            color: #FFFFFF;
            font-family: inherit;
            line-height: 1.55;
        }
        @media (max-width: 900px) {
            .tr-todo-grid {
                grid-template-columns: 1fr;
            }
            .tr-todo-card,
            .tr-todo-detail-card {
                grid-column: 1 !important;
                grid-row: auto !important;
            }
            .tr-todo-detail-card {
                max-height: none;
            }
        }
        @media (max-width: 760px) {
            .tr-reference, .tr-work-top, .tr-schedule-row {
                align-items: flex-start;
                flex-direction: column;
            }
            .tr-work-grid {
                grid-template-columns: 1fr;
            }
            .tr-chat-row {
                max-width: 92%;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
