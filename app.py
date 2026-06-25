from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import streamlit as st

from notification_provider import PreviewNotificationProvider
from task_extractor import analyze_text


SAMPLE_PATH = Path(__file__).with_name("sample_chat.txt")


def main() -> None:
    st.set_page_config(page_title="신입 업무 레이더 Agent", layout="wide")

    default_mode = os.getenv("TASKRADAR_MODE", "local")
    with st.sidebar:
        mode = st.radio("앱 모드", ["local", "demo"], index=0 if default_mode != "demo" else 1)
        st.caption("demo 모드는 실제 카카오 발송/토큰 기능을 숨기고 알림 미리보기만 표시합니다.")
        provider_status = _provider_status()
        st.info(provider_status)

    st.title("신입 업무 레이더 Agent")
    st.write("카카오톡 대화 내보내기 `.txt`를 분석해 추천 문구, To-do, 일정 후보, 오전 8시 알림 미리보기를 만듭니다.")

    reference_date = st.date_input("기준일", value=date.today())

    sample_text = SAMPLE_PATH.read_text(encoding="utf-8") if SAMPLE_PATH.exists() else ""
    uploaded = st.file_uploader("카카오톡 대화 내보내기 .txt 업로드", type=["txt"])
    use_sample = st.toggle("샘플 대화 사용", value=mode == "demo")

    raw_text = sample_text if use_sample else ""
    if uploaded:
        raw_text = uploaded.read().decode("utf-8-sig")

    raw_text = st.text_area("대화 내용", value=raw_text, height=220, placeholder="[선배] 이번 주 금요일 오전 10시에 발표 리허설 있어요.")

    if st.button("분석하기", type="primary", use_container_width=True):
        if not raw_text.strip():
            st.warning("분석할 대화 내용을 업로드하거나 입력해 주세요.")
            return
        with st.spinner("대화에서 업무 신호를 찾는 중입니다..."):
            st.session_state["analysis_raw"] = raw_text
            st.session_state["analysis_ref"] = reference_date
            st.session_state["analysis_result"] = analyze_text(raw_text, reference_date)

    result = st.session_state.get("analysis_result")
    if not result:
        _render_empty_state(mode)
        return

    _render_result(result, mode)

    st.divider()
    st.subheader("선배 답변 재입력")
    st.write("추천 문구를 보낸 뒤 받은 답변이 있으면 여기에 붙여넣으세요. 없으면 건너뛰어도 됩니다.")
    senior_reply = st.text_area("선배 답변", height=100, placeholder="예: 양식은 PPT 5장 이내고, 팀즈 과제방에 올려주세요.")
    if st.button("답변 반영하기", use_container_width=True):
        raw = st.session_state.get("analysis_raw", raw_text)
        ref = st.session_state.get("analysis_ref", reference_date)
        with st.spinner("선배 답변을 반영해 To-do를 업데이트하는 중입니다..."):
            st.session_state["analysis_result"] = analyze_text(raw, ref, senior_reply=senior_reply)
        st.rerun()


def _provider_status() -> str:
    if os.getenv("GEMMA_API_URL"):
        return "Gemma 서버 provider가 설정되어 있습니다."
    if os.getenv("OPENAI_API_KEY"):
        return "OpenAI provider가 설정되어 있습니다."
    return "API 키가 없어 규칙 기반 데모 폴백으로 동작합니다."


def _render_empty_state(mode: str) -> None:
    if mode == "demo":
        st.info("샘플 대화를 사용해 바로 분석 결과를 확인할 수 있습니다.")
    else:
        st.info("카카오톡 대화 내보내기 파일을 업로드하거나 대화 내용을 붙여넣고 분석을 시작하세요.")


def _render_result(result, mode: str) -> None:
    st.caption(f"분석 provider: {result.provider}")
    tabs = st.tabs(["요약", "업무 요청", "추천 문구", "To-do/일정", "알림 미리보기", "JSON"])

    with tabs[0]:
        st.subheader("대화 요약")
        st.write(result.summary)
        if result.senior_reply_update:
            st.success(result.senior_reply_update)

    with tabs[1]:
        st.subheader("업무 요청 및 확인 필요사항")
        rows = []
        for item in result.items:
            rows.append(
                {
                    "유형": item.type,
                    "제목": item.title,
                    "분류": item.classification,
                    "기한/일시": item.due or item.datetime_start or "확인 필요",
                    "확실도": item.date_confidence,
                    "위험도": f"{item.miss_risk_level} ({item.miss_risk_score})",
                    "애매한 점": ", ".join(item.ambiguities),
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

    with tabs[2]:
        st.subheader("선배에게 보낼 추천 문구")
        st.text_area("취합 문구", value=result.questions_to_senior, height=180)
        for message in result.recommended_messages:
            st.code(message, language="text")

    with tabs[3]:
        todo_items = [item for item in result.items if item.type != "일정"]
        schedule_items = [item for item in result.items if item.type == "일정"]
        left, right = st.columns(2)
        with left:
            st.subheader("To-do")
            for item in todo_items:
                with st.expander(item.title, expanded=True):
                    st.write(f"기한: {item.due or '확인 필요'}")
                    if item.resolved_details:
                        st.json(item.resolved_details)
                    st.write("체크리스트")
                    for checklist in item.checklist:
                        st.checkbox(checklist, key=f"{item.id}-{checklist}")
        with right:
            st.subheader("일정 후보")
            for item in schedule_items:
                st.write(f"- {item.title}: {item.datetime_start or '확인 필요'} ({item.classification})")

    with tabs[4]:
        provider = PreviewNotificationProvider()
        preview = provider.build_preview(result.morning_notification_preview)
        st.subheader(preview.channel)
        st.write(f"발송 예정: {preview.send_time}")
        st.text_area("발송될 문구", value=preview.message, height=220)
        if mode == "demo":
            st.caption("웹 데모에서는 실제 카카오톡 발송을 하지 않습니다.")
        else:
            st.caption("로컬 2차 확장에서 카카오 나에게 보내기 provider로 실제 발송을 연결합니다.")

    with tabs[5]:
        st.json(result.to_dict())


if __name__ == "__main__":
    main()
