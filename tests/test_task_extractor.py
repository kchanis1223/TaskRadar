from datetime import date

from task_extractor import analyze_text


SAMPLE = """[선배] 이번 주 금요일 오전 10시에 팀별 발표 리허설 있어요.
[선배] 발표자료는 목요일 퇴근 전까지 제출해주세요.
[선배] 그리고 AI Agent 아이디어는 내일까지 3개 정도 정리해서 공유 부탁드립니다.
[나] 네, 확인했습니다.
[선배] 제출 양식은 추후 공유드릴게요.
"""


def test_fallback_analysis_extracts_schedule_todo_and_questions(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)

    result = analyze_text(SAMPLE, date(2026, 6, 24))

    assert result.provider == "fallback"
    assert any(item.type == "일정" for item in result.items)
    assert any(item.type == "할일" for item in result.items)
    assert "발표자료" in result.questions_to_senior
    assert "오늘 오전 8시" in result.morning_notification_preview


def test_senior_reply_updates_todo_details(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)

    result = analyze_text(SAMPLE, date(2026, 6, 24), senior_reply="양식은 PPT 5장 이내고, 팀즈 과제방에 올려주세요.")

    todos = [item for item in result.items if item.type == "할일"]
    assert any(item.resolved_details.get("양식") == "PPT" for item in todos)
    assert any(item.resolved_details.get("제출 경로") == "팀즈 과제방" for item in todos)
    assert result.senior_reply_update
