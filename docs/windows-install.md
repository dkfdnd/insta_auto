# 새 Windows PC 설치 가이드: 세 저장소 함께 사용하기

이 문서는 새 PC에서 **독립적인** 수집·제작 환경을 만드는 순서다. Git은 코드와 `influencer_list.txt`를 옮기지만 로그인, 수집 DB, 영상, 대본 작업 기록, 모델, CapCut 초안은 옮기지 않는다. 기존 작업을 이어야 한다면 아래의 [작업 데이터 이전](#작업-데이터-이전)을 먼저 읽는다.

## 1. 준비와 복제

- Windows 10/11 64비트, Git, Python 3.10 64비트와 Python Launcher(`py`), Google Chrome을 준비한다. 세 프로젝트의 Python 환경은 **각각 따로** 만든다.
- VoiceBench에는 NVIDIA GPU와 드라이버가 필요하다. Qwen 설치 가이드는 VRAM 8GB 이상을 권장한다. 모델과 영상 때문에 여유 저장 공간을 충분히 확보한다.
- FFmpeg와 FFprobe를 PATH에서 실행할 수 있게 설치하고, 편집할 PC에는 CapCut Desktop을 설치한다. GitHub 저장소에 접근 권한이 필요한 경우 새 PC에서 Git 인증도 준비한다.
- 세 저장소를 같은 상위 폴더에 둔다. 아래 예시는 현재 사용자 프로필 아래에 만들며, 쓰기 권한이 있는 짧은 영문 경로를 선택해도 된다.

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\ReelsWorkspace" | Out-Null
Set-Location "$env:USERPROFILE\ReelsWorkspace"
git clone https://github.com/dkfdnd/insta_auto.git insta_auto
git clone https://github.com/dkfdnd/VoiceBench.git VoiceBench
git clone https://github.com/dkfdnd/auto_capcut.git auto_capcut
```

`VoiceBench`는 `Voice`라는 폴더명도 지원한다. 대본은 insta_auto 안의 Codex CLI 연결을 사용한다. script_auto는 설치하지 않는다. [내장 집필 안내](writing.md)를 참고한다.

## 2. PC별 실행 환경 설치

아래 명령은 위에서 만든 `ReelsWorkspace`를 기준으로 한다. 먼저 대본·음성·편집 환경을 준비한 뒤 Hotpost를 시작한다.

공식 Codex CLI를 설치하고 실행 계정으로 로그인한다. `codex login status`가 로그인 상태를 반환해야 한다. 대본용 로컬 모델 다운로드와 별도 대본 서버는 필요 없다.

```powershell
Set-Location "$env:USERPROFILE\ReelsWorkspace\VoiceBench"
.\setup-windows.cmd -DownloadModels
```

개인 목소리를 쓸 경우 `selected_reference.wav`와 실제 발화의 `selected_reference.txt`를 [VoiceBench 설치 가이드](https://github.com/dkfdnd/VoiceBench/blob/main/docs/windows-install.md)에 따라 **안전하게** 복사한다. 이 설치 명령은 Qwen 환경을 준비한다. ZONOS2와 공식 목소리는 별도 설치이며 GPU별 CUDA 아키텍처·VRAM을 확인해야 한다. Hotpost 연결용 키는 새 PC에서 아래처럼 로컬 전용 서버를 한 번 시작해 생성한다. 웹 비밀번호 입력창이 나오지만 그 값이나 생성된 키를 Git에 넣지 않는다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\host.ps1 -BindAddress 127.0.0.1 -NoTunnel -Background
```

```powershell
Set-Location "$env:USERPROFILE\ReelsWorkspace\auto_capcut"
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m auto_capcut.doctor
```

`doctor`는 CapCut이 **완전히 종료된 상태**여야 `ready: true`를 반환한다. FFmpeg/FFprobe, CapCut 설치, 초안 폴더도 검사한다. 자세한 내용은 [편집기 설치 가이드](https://github.com/dkfdnd/auto_capcut/blob/main/docs/windows-install.md).

```powershell
Set-Location "$env:USERPROFILE\ReelsWorkspace\insta_auto"
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 3. 설정·인증·첫 실행

`config.json`의 수집·자동 제작 설정을 확인한다. `studio_url`, `studio_root`, `studio_api_key_file`은 과거 설정 파일 호환용이며 사용하지 않는다. Codex가 설치·로그인되지 않았으면 대본 실행 오류로 표시하고 다른 모델로 대체하지 않는다.

```powershell
Set-Location "$env:USERPROFILE\ReelsWorkspace\insta_auto"
.\.venv\Scripts\python.exe -X utf8 -m hotpost login --browser dedicated
.\start-local.cmd
```

새 PC의 전용 Chrome에서 Instagram 인증을 완료한다. 다른 PC의 Chrome 로그인이나 쿠키가 자동으로 전달되지는 않는다. `start-local.cmd`는 Codex 실행 환경을 확인하고 음성·Hotpost 서버를 시작하거나 기존 정상 서버를 재사용하지만 **수집은 하지 않는다**. CapCut이 열려 있으면 편집 준비 검사가 실패할 수 있다. 연결 점검 주소는 `http://127.0.0.1:8775/api/production-health`, 화면은 `http://127.0.0.1:8775/`이다. 접속만 되고 대본·음성·편집 점검이 실패하면 각 서비스의 키, 포트, 설치 경로를 먼저 확인한다.

계정 하나로 수집과 화면 반영을 검증한 뒤 전체 수집을 실행한다. 수집은 외부 서비스 요청이므로 연속 재시도로 CAPTCHA나 429를 유발하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m hotpost run --only 계정명
.\.venv\Scripts\python.exe -m hotpost run
```

## 4. 오전 7시 예약

Windows 작업 스케줄러 등록은 Git으로 이전되지 않는다. 실제 수집·제작 설정이 맞는지 확인한 **각 PC에서** 따로 설치한다. 현지 시간 오전 7시 기준이며 PC가 꺼졌거나 사용자가 로그아웃했으면 정각 실행을 보장하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m hotpost schedule status
.\.venv\Scripts\python.exe -m hotpost schedule install --hour 7 --minute 0
.\.venv\Scripts\python.exe -m hotpost schedule status
```

두 PC가 같은 Instagram 계정으로 동시에 수집하면 요청이 겹쳐 제한이나 CAPTCHA가 늘 수 있다. 둘 다 독립 수집하려면 실행 시간을 엇갈리게 정하고 각 PC에서 자신의 인증·로그를 확인한다.

## 작업 데이터 이전

| 위치 | Git 복제 후 상태 | 이어서 작업하려면 |
|---|---|---|
| `insta_auto/data/` | DB, 제작 이력, 영상, 대본, 세션 없음 | 기존 PC에서 필요한 DB·제작 파일·영상의 별도 백업을 준비한다. 경로 참조를 새 PC에서 확인하고 Instagram은 다시 로그인한다. |
| `VoiceBench/data/`, `.runtime/` | 음성 결과·개인 참조·모델·API 키 없음 | 개인 WAV/TXT를 안전하게 복사하고 모델·엔진·키는 새 PC에서 설치·생성한다. 가상환경이나 GPU 빌드를 통째로 복사하지 않는다. |
| `auto_capcut/works/`, `%LOCALAPPDATA%\CapCut` | 영상 소재·사용자 편집 초안 없음 | 편집 중인 소재와 CapCut 초안은 별도 백업한다. 초안의 원본 파일 경로와 로컬 효과 캐시를 새 PC에서 다시 확인한다. |

두 PC를 계속 독립 운영한다면 DB를 한 번 복사한 뒤 자동 동기화된다고 생각하면 안 된다. Git으로 공유되는 계정 목록 외의 수집·제작 기록은 PC별로 갈라진다. `.venv`, 브라우저 쿠키, 비밀번호, API 키를 Git에 추가하지 않는다.

## 문제를 좁히는 순서

1. `git status --short`와 각 저장소의 가상환경·모델 설치 여부를 확인한다.
2. CapCut을 닫고 `auto_capcut`의 `doctor`, VoiceBench의 인증된 `/v1/health`, `codex login status`를 확인한다.
3. Hotpost의 `/api/production-health`에서 실패한 서비스를 본다. `start-local.cmd` 실행 로그는 `insta_auto/data/local-services/`에 남는다.
4. Instagram 오류는 [로그인·수집 문제 해결](../README.md#문제-해결)을 확인한다. 새 PC에서 첫 수집 전에는 대시보드 데이터가 없는 것이 정상이다.

각 저장소의 세부 설치·운영법은 [내장 대본](writing.md), [음성](https://github.com/dkfdnd/VoiceBench/blob/main/docs/windows-install.md), [편집](https://github.com/dkfdnd/auto_capcut/blob/main/docs/windows-install.md) 가이드에 있다.
