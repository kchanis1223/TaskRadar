# TaskRadar

신입 업무 레이더 Agent MVP입니다. 카카오톡 대화 내보내기 `.txt` 파일을 업로드하면 업무 요청, 애매한 표현, 선배에게 보낼 추천 문구, To-do, 일정 후보, 오전 8시 알림 미리보기를 생성합니다.

## 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 모드

- `local`: 로컬 사용 흐름 중심. 파일 업로드와 샘플 대화를 모두 지원하며, 향후 카카오 나에게 보내기 provider를 붙일 수 있는 구조입니다.
- `demo`: 제출용 웹 데모. 실제 발송/토큰 UI 없이 알림 미리보기만 보여줍니다.

환경변수 `TASKRADAR_MODE=demo` 또는 사이드바에서 모드를 바꿀 수 있습니다.

## LLM Provider

- `OPENAI_API_KEY`가 있으면 OpenAI provider를 먼저 시도합니다.
- `GEMMA_API_URL`이 있으면 같은 JSON 스키마를 반환하는 Gemma 서버 provider를 시도할 수 있습니다.
- 둘 다 없거나 실패하면 규칙 기반 데모 폴백으로 동작합니다.

## 테스트

```bash
pytest
```
