# TaskRadar local server deployment

이 배포 방식은 현재 PC를 서버로 사용합니다. 사용자는 웹주소로 접속하고, 분석 요청은 이 PC의 Streamlit 앱이 받은 뒤 로컬 `opencode run`으로 처리합니다.

## 구조

사용자 브라우저 -> 공개 URL 또는 공유기 포트포워딩 -> 현재 PC의 Streamlit 서버 -> 현재 PC의 opencode CLI -> 분석 결과 반환

## 1. opencode 로그인 확인

서버로 쓸 Windows 계정에서 먼저 opencode 로그인이 되어 있어야 합니다.

```powershell
opencode providers login anthropic
opencode --version
```

`opencode --version`이 안 되면 `TASKRADAR_OPENCODE_COMMAND`에 `opencode.exe` 전체 경로를 넣습니다.

## 2. 서버용 .env

프로젝트 루트에 `.env`를 두고 아래처럼 설정합니다.

```env
TASKRADAR_MODE=demo
TASKRADAR_USE_OPENCODE=1
TASKRADAR_REQUIRE_OPENCODE=1
TASKRADAR_OPENCODE_COMMAND=opencode
TASKRADAR_OPENCODE_MODEL=openai/gpt-5.4-mini
TASKRADAR_OPENCODE_TIMEOUT=180
TASKRADAR_OPENCODE_WORK_DIR=C:\Temp\taskradar-opencode-work
TASKRADAR_ACCESS_PASSWORD=change-this-password
```

`TASKRADAR_REQUIRE_OPENCODE=1`은 opencode가 실패했을 때 규칙 기반 결과로 조용히 넘어가지 않게 막습니다.

## 3. 최초 설치

```powershell
cd "$env:USERPROFILE\OneDrive\Desktop\TaskRadar\TaskRadar"
.\scripts\setup_server.ps1
```

## 4. 서버 실행

```powershell
.\scripts\start_server.ps1 -Port 8501
```

PC 내부에서는 `http://localhost:8501`로 확인합니다. Cloudflare Tunnel을 쓰는 경우 기본값인 `127.0.0.1`로 충분합니다. 같은 와이파이/사내망에서 직접 접속을 허용해야 할 때만 `-Address 0.0.0.0`으로 실행합니다.

## 5. 고정 일반 URL로 공개하기

사용자가 `https://taskradar.example.com` 같은 일반 URL로 접속하게 하려면 Cloudflare Tunnel + 커스텀 도메인을 권장합니다.

이 방식의 장점:

- 공유기 포트포워딩이 필요 없습니다.
- HTTPS가 자동으로 붙습니다.
- PC의 실제 공인 IP를 직접 노출하지 않아도 됩니다.
- 서버 PC의 `opencode` 로그인 상태를 그대로 사용할 수 있습니다.

준비물:

- 소유한 도메인
- Cloudflare 계정
- 도메인의 DNS를 Cloudflare에서 관리하도록 설정
- 서버 PC에 `cloudflared` 설치

설정 흐름:

1. Cloudflare 대시보드에서 Zero Trust -> Networks -> Tunnels로 이동합니다.
2. 새 Tunnel을 만들고 Connector 타입은 `cloudflared`를 선택합니다.
3. Windows용 설치/실행 명령을 서버 PC PowerShell에서 실행합니다.
4. Public Hostname을 추가합니다.
   - Subdomain: `taskradar`
   - Domain: 본인 도메인
   - Service type: `HTTP`
   - URL: `localhost:8501`
5. TaskRadar 서버를 실행합니다.

```powershell
.\scripts\start_server.ps1 -Port 8501
```

기본 실행 주소는 `127.0.0.1`입니다. Cloudflare Tunnel이 같은 PC에서 `localhost:8501`로 붙기 때문에 Streamlit을 외부 네트워크에 직접 열 필요가 없습니다.

6. 사전 점검을 실행합니다.

```powershell
.\scripts\check_public_url_prereqs.ps1 -Port 8501
```

PowerShell 실행 정책 때문에 스크립트가 막히면 아래처럼 실행합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_public_url_prereqs.ps1 -Port 8501
```

이후 사용자는 아래처럼 접속합니다.

```text
https://taskradar.example.com
```

현재 이미 8501/8502가 사용 중이면 8503 같은 다른 포트로 실행하고, Cloudflare Public Hostname의 URL도 같은 포트로 맞춥니다.

```powershell
.\scripts\start_server.ps1 -Port 8503
```

Cloudflare Public Hostname URL:

```text
localhost:8503
```

## 6. 공개 전 보안 체크

최소 권장 설정:

- `TASKRADAR_ACCESS_PASSWORD`를 강한 비밀번호로 설정합니다.
- 가능하면 Cloudflare Access를 Public Hostname 앞에 붙여 허용된 이메일/계정만 접속하게 합니다.
- Streamlit은 기본값인 `127.0.0.1`로 실행합니다. Cloudflare Tunnel 사용 시 `0.0.0.0`으로 열 필요가 없습니다.
- `.env`, 로그 파일, 업로드 샘플, 테스트 대화 파일을 저장소에 올리지 않습니다.
- 서버 PC 절전 모드를 끄고, Windows 계정 잠금/암호를 유지합니다.
- 공개 URL을 넓게 공유하기 전에 소수 사용자로만 먼저 테스트합니다.

현재 구조의 주요 리스크:

- URL과 비밀번호가 유출되면 누구나 서버 PC의 `opencode` 사용량을 소모할 수 있습니다.
- 업로드된 카카오톡 대화 내용은 분석을 위해 서버 PC와 opencode provider를 거칩니다.
- 앱 프로세스는 서버 PC의 사용자 계정 권한으로 실행됩니다. 서버 PC에서 민감한 파일을 같이 다루지 않는 것이 좋습니다.
- Streamlit 앱 내부 비밀번호에는 계정별 권한, 실패 횟수 제한, 감사 로그가 없습니다. 공개 범위가 넓어지면 Cloudflare Access 같은 앞단 인증이 필요합니다.
- `TASKRADAR_OPENCODE_WORK_DIR`에는 `.env`, 소스코드, 개인 문서를 두지 않습니다.

## 7. 임시 URL로 빠르게 공개하기

가장 간단한 방식은 터널 도구를 쓰는 것입니다.

```powershell
cloudflared tunnel --url http://localhost:8501
```

또는:

```powershell
ngrok http 8501
```

공유기 포트포워딩으로 직접 공개할 수도 있지만, Windows 방화벽 인바운드 허용, 공유기 포트포워딩, 공인 IP 또는 DDNS 설정이 필요합니다.

## 운영 주의사항

- 서버 PC가 꺼지거나 절전 모드에 들어가면 서비스도 중단됩니다.
- `.env`는 공유하거나 git에 올리지 않습니다.
- 공개 URL을 넓게 공유할 계획이면 `TASKRADAR_ACCESS_PASSWORD`를 반드시 설정합니다.
- 업로드된 대화 내용은 분석을 위해 서버 PC의 opencode provider로 전달됩니다.
- 많은 사람이 동시에 쓰면 opencode 호출이 느려지거나 provider 사용량이 증가할 수 있습니다.
