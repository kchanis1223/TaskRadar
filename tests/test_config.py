import os

from config import configured_provider_label, load_local_env


def test_load_local_env_reads_operator_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKRADAR_DISABLE_ENV_FILE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-test-from-env\nOPENAI_MODEL=gpt-4o-mini\n", encoding="utf-8")

    load_local_env(env_path)

    assert os.getenv("OPENAI_API_KEY") == "sk-test-from-env"
    assert os.getenv("OPENAI_MODEL") == "gpt-4o-mini"


def test_load_local_env_strips_utf8_bom_from_first_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TASKRADAR_DISABLE_ENV_FILE", raising=False)
    monkeypatch.delenv("TASKRADAR_USE_OPENCODE", raising=False)

    env_path = tmp_path / ".env"
    env_path.write_text("\ufeffTASKRADAR_USE_OPENCODE=1\n", encoding="utf-8")

    load_local_env(env_path)

    assert os.getenv("TASKRADAR_USE_OPENCODE") == "1"


def test_provider_label_hides_provider_details_by_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    assert configured_provider_label() == "AI 분석 준비됨"


def test_provider_label_supports_opencode_oauth(monkeypatch):
    monkeypatch.setenv("TASKRADAR_USE_OPENCODE", "1")
    monkeypatch.setenv("TASKRADAR_OPENCODE_MODEL", "anthropic/claude-haiku-4-5")
    monkeypatch.setattr("config._command_exists", lambda command: True)

    assert configured_provider_label() == "AI 분석 준비됨"


def test_provider_label_warns_when_opencode_command_is_missing(monkeypatch):
    monkeypatch.setenv("TASKRADAR_USE_OPENCODE", "1")
    monkeypatch.setattr("config._command_exists", lambda command: False)

    assert configured_provider_label() == "AI 설정 확인 필요 · opencode 실행 파일 없음"


def test_provider_label_debug_shows_non_secret_details(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("TASKRADAR_DEBUG", "1")

    label = configured_provider_label()

    assert "OpenAI" in label
    assert "gpt-4o-mini" in label
    assert "sk-test-secret" not in label
