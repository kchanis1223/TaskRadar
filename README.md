# TaskRadar

신입 업무 레이더 Agent MVP입니다. 카카오톡 대화 내보내기 `.txt` 파일을 업로드하면 업무 요청, 애매한 표현, 선배에게 보낼 추천 문구, To-do, 일정 후보, 오전 8시 알림 미리보기를 생성합니다.

## 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

현재 PC를 서버로 사용해 `https://taskradar.example.com` 같은 일반 URL로 공유하려면 [DEPLOY_LOCAL_SERVER.md](DEPLOY_LOCAL_SERVER.md)를 참고하세요.

## 모드

- `local`: 로컬 사용 흐름 중심. 파일 업로드와 샘플 대화를 모두 지원하며, 향후 카카오 나에게 보내기 provider를 붙일 수 있는 구조입니다.
- `demo`: 제출용 웹 데모. 실제 발송/토큰 UI 없이 알림 미리보기만 보여줍니다.

환경변수 `TASKRADAR_MODE=demo` 또는 사이드바에서 모드를 바꿀 수 있습니다.

## LLM Provider

- 프로젝트 루트의 `.env` 파일을 자동으로 읽습니다.
- `TASKRADAR_USE_OPENCODE=1`이면 로컬 `opencode run`을 먼저 시도합니다. 이 경우 `opencode providers login anthropic`으로 인증된 Claude/Anthropic OAuth 세션을 opencode가 처리합니다.
- `TASKRADAR_REQUIRE_OPENCODE=1`이면 opencode 실패 시 다른 provider나 규칙 기반 폴백으로 넘어가지 않고 연결 실패를 표시합니다.
- `TASKRADAR_ACCESS_PASSWORD`를 설정하면 공개 웹 접속 전에 비밀번호 입력 화면을 표시합니다.
- `OPENAI_API_KEY`가 있으면 OpenAI provider를 먼저 시도합니다.
- `OPENAI_MODEL`로 모델을 바꿀 수 있습니다. 기본값은 `gpt-4o-mini`입니다.
- `ANTHROPIC_API_KEY`가 있으면 OpenAI 다음으로 Anthropic provider를 시도합니다.
- `ANTHROPIC_MODEL`로 모델을 바꿀 수 있습니다. 기본값은 `claude-3-5-haiku-latest`입니다.
- `GEMMA_API_URL`이 있으면 같은 JSON 스키마를 반환하는 Gemma 서버 provider를 시도합니다.
- 둘 다 없거나 실패하면 규칙 기반 데모 폴백으로 동작합니다.
- 데모 서비스에서는 API key를 사용자에게 입력받지 않습니다. 운영자가 서버 `.env` 또는 배포 secret에만 저장합니다.
- 사용자 화면에는 API key, provider 원문 오류, 내부 로그가 표시되지 않습니다.
- `TASKRADAR_DEBUG=1`일 때만 provider명과 축약된 오류 종류를 개발 확인용으로 표시합니다.

`.env` 예시:

```bash
OPENAI_API_KEY=sk-your-api-key
OPENAI_MODEL=gpt-4o-mini
# 또는 로컬 opencode OAuth 사용
TASKRADAR_USE_OPENCODE=1
TASKRADAR_OPENCODE_COMMAND=opencode
TASKRADAR_OPENCODE_MODEL=openai/gpt-5.4-mini
# 또는
ANTHROPIC_API_KEY=sk-ant-your-api-key
ANTHROPIC_MODEL=claude-3-5-haiku-latest
```

## 테스트

```bash
pytest
```
