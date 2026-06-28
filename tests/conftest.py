import pytest


@pytest.fixture(autouse=True)
def disable_env_file_loading(monkeypatch):
    monkeypatch.setenv("TASKRADAR_DISABLE_ENV_FILE", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMMA_API_URL", raising=False)
    monkeypatch.delenv("TASKRADAR_DEBUG", raising=False)
    monkeypatch.delenv("TASKRADAR_USE_OPENCODE", raising=False)
    monkeypatch.delenv("TASKRADAR_REQUIRE_OPENCODE", raising=False)
    monkeypatch.delenv("TASKRADAR_OPENCODE_COMMAND", raising=False)
    monkeypatch.delenv("TASKRADAR_OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("TASKRADAR_TEMP_DIR", raising=False)
    monkeypatch.delenv("TASKRADAR_ACCESS_PASSWORD", raising=False)
