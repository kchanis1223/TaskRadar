import json
import sys
from datetime import date
from types import ModuleType, SimpleNamespace

from app import _public_result_dict
from models import AnalysisItem, AnalysisResult
from task_extractor import analyze_text, update_result_with_senior_reply


SAMPLE = "[선배] 내일까지 회의 자료를 정리해서 공유해 주세요."
FAKE_OPENAI_KEY = "sk-test-secret-openai"
FAKE_ANTHROPIC_KEY = "sk-ant-test-secret"


def _provider_data():
    return {
        "summary": "회의 자료 정리 요청이 확인되었습니다.",
        "items": [
            {
                "id": "t1",
                "raw_text": "내일까지 회의 자료를 정리해서 공유해 주세요.",
                "type": "할일",
                "title": "회의 자료 정리 및 공유",
                "datetime_start": None,
                "due": "2026-06-25T09:00",
                "date_confidence": "높음",
                "classification": "후보",
                "importance": "중간",
                "ambiguities": [],
                "suggested_question": "공유 대상과 형식을 확인드려도 될까요?",
                "checklist": ["회의 자료 정리", "공유 대상 확인"],
            }
        ],
        "recommended_messages": ["공유 대상과 형식을 확인드려도 될까요?"],
        "questions_to_senior": "- 공유 대상과 형식을 확인드려도 될까요?",
    }


def test_openai_provider_uses_operator_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI_KEY)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)

    fake_openai = ModuleType("openai")

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["response_format"] == {"type": "json_object"}
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(_provider_data(), ensure_ascii=False))
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, timeout):
            self.timeout = timeout
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    result = analyze_text(SAMPLE, date(2026, 6, 24))

    assert result.provider == "openai"
    assert result.provider_error == ""
    assert FAKE_OPENAI_KEY not in str(result.to_dict())


def test_opencode_provider_uses_cli_without_prompt_in_args(monkeypatch, tmp_path):
    monkeypatch.setenv("TASKRADAR_USE_OPENCODE", "1")
    monkeypatch.setenv("TASKRADAR_OPENCODE_COMMAND", "fake-opencode")
    monkeypatch.setenv("TASKRADAR_OPENCODE_MODEL", "anthropic/claude-haiku-4-5")
    monkeypatch.setenv("TASKRADAR_TEMP_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)
    monkeypatch.setattr("task_extractor._command_exists", lambda command: command == "fake-opencode")

    captured = {}

    def fake_run(args, cwd, capture_output, text, encoding, errors, timeout, check):
        captured["args"] = args
        prompt_file = tmp_path / next(path.name for path in tmp_path.iterdir())
        captured["prompt_file"] = prompt_file
        assert prompt_file.exists()
        assert SAMPLE in prompt_file.read_text(encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=json.dumps(_provider_data(), ensure_ascii=False), stderr="")

    monkeypatch.setattr("task_extractor.subprocess.run", fake_run)

    result = analyze_text(SAMPLE, date(2026, 6, 24))

    assert result.provider == "opencode-cli"
    assert captured["args"][0] == "fake-opencode"
    assert "--file" in captured["args"]
    assert SAMPLE not in " ".join(captured["args"])
    assert not captured["prompt_file"].exists()


def test_opencode_patch_updates_selected_todo_only(monkeypatch, tmp_path):
    monkeypatch.setenv("TASKRADAR_USE_OPENCODE", "1")
    monkeypatch.setenv("TASKRADAR_OPENCODE_COMMAND", "fake-opencode")
    monkeypatch.setenv("TASKRADAR_OPENCODE_MODEL", "openai/gpt-5.4-mini")
    monkeypatch.setenv("TASKRADAR_TEMP_DIR", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)
    monkeypatch.setattr("task_extractor._command_exists", lambda command: command == "fake-opencode")

    result = AnalysisResult(
        summary="업무 분석",
        reference_date=date(2026, 6, 28),
        items=[
            AnalysisItem(
                id="t1",
                raw_text="AI Agent 아이디어 양식은 추후 공유",
                type="할일",
                title="AI Agent 아이디어 정리",
                due="2026-06-29T09:00",
                ambiguities=["양식 미확정"],
                checklist=["아이디어 정리"],
            ),
            AnalysisItem(
                id="t2",
                raw_text="발표자료 제출",
                type="할일",
                title="발표자료 제출",
                due="2026-06-30T18:00",
                checklist=["발표자료 작성"],
            ),
        ],
        recommended_messages=[],
        questions_to_senior="",
        morning_notification_preview="",
    )

    captured = {}

    def fake_run(args, cwd, capture_output, text, encoding, errors, timeout, check):
        captured["args"] = args
        prompt_file = tmp_path / next(path.name for path in tmp_path.iterdir())
        prompt = prompt_file.read_text(encoding="utf-8")
        captured["prompt"] = prompt
        assert "AI Agent 아이디어 정리" in prompt
        assert "발표자료 제출" not in prompt
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "updates": [
                        {
                            "id": "t1",
                            "classification": "확인필요",
                            "resolved_details": {"상태": "자료 재전달 대기"},
                            "ambiguities": ["선배가 자료를 다시 보내기로 했으므로 수신 후 재확인 필요"],
                            "suggested_question": "네, 자료 보내주시면 확인하고 다시 정리하겠습니다.",
                            "checklist_add": ["선배가 다시 보내는 자료 확인"],
                        }
                    ],
                    "senior_reply_update": "선택한 To-Do에 자료 재전달 대기 상태를 반영했습니다.",
                },
                ensure_ascii=False,
            ),
            stderr="",
        )

    monkeypatch.setattr("task_extractor.subprocess.run", fake_run)

    updated = update_result_with_senior_reply(
        result,
        "내가 다시 보내줄게. 다시 확인해봐.",
        target_item_ids=["t1"],
    )

    first = updated.items[0]
    second = updated.items[1]

    assert first.resolved_details["상태"] == "자료 재전달 대기"
    assert first.due == "2026-06-29T09:00"
    assert first.suggested_question == "네, 자료 보내주시면 확인하고 다시 정리하겠습니다."
    assert "선배가 다시 보내는 자료 확인" in first.checklist
    assert second.resolved_details == {}
    assert "Senior Reply Patch" in " ".join(captured["args"])
    assert "내가 다시 보내줄게" not in " ".join(captured["args"])


def test_required_opencode_does_not_fallback_when_cli_is_missing(monkeypatch):
    monkeypatch.setenv("TASKRADAR_USE_OPENCODE", "1")
    monkeypatch.setenv("TASKRADAR_REQUIRE_OPENCODE", "1")
    monkeypatch.setenv("TASKRADAR_OPENCODE_COMMAND", "missing-opencode")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)
    monkeypatch.setattr("task_extractor._command_exists", lambda command: False)

    result = analyze_text(SAMPLE, date(2026, 6, 24))

    assert result.provider == "opencode-unavailable"
    assert result.items == []
    assert result.provider_error
    assert result.warnings == ["opencode_cli: RuntimeError"]


def test_provider_failure_does_not_expose_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_OPENAI_KEY)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)

    fake_openai = ModuleType("openai")

    class FakeCompletions:
        def create(self, **kwargs):
            raise RuntimeError(f"authentication failed for {FAKE_OPENAI_KEY}")

    class FakeOpenAI:
        def __init__(self, timeout):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    fake_openai.OpenAI = FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    result = analyze_text(SAMPLE, date(2026, 6, 24))
    public = _public_result_dict(result)

    assert result.provider == "fallback"
    assert result.provider_error
    assert result.warnings == ["openai: RuntimeError"]
    assert FAKE_OPENAI_KEY not in str(result.to_dict())
    assert "provider" not in public
    assert "provider_error" not in public
    assert "warnings" not in public


def test_anthropic_provider_uses_operator_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_ANTHROPIC_KEY)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "content": [
                    {"type": "text", "text": json.dumps(_provider_data(), ensure_ascii=False)}
                ]
            }

    def fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json
        return FakeResponse()

    monkeypatch.setattr("task_extractor.requests.post", fake_post)

    result = analyze_text(SAMPLE, date(2026, 6, 24))

    assert result.provider == "anthropic"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == FAKE_ANTHROPIC_KEY
    assert FAKE_ANTHROPIC_KEY not in str(result.to_dict())
