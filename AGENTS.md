# Hotpost 작업 가이드

이 저장소는 Instagram 계정별 최근 게시물을 수집해 평소 대비 급상승한 게시물을 보여주고,
선택한 릴스의 소스 영상 후보와 대본을 별도 작업으로 생성한다. 사용자용 시작 방법은
`README.md`, 상세 파이프라인은 `docs/source_video_pipeline.md`와
`docs/transcript_pipeline.md`를 참고한다.

## 시작할 때

- `git status --short`로 기존 변경사항을 확인하고 다른 작업을 덮어쓰지 않는다.
- `hotpost/config.py`의 `Settings`와 `config.json`/`HOTPOST_*` 환경변수 우선순위를 확인한다.
- `data/`는 DB, Instagram 세션, 플랫폼 쿠키, 다운로드 영상, ML 모델, 대본이 있는 로컬 상태이며 Git에서 제외된다. 커밋하거나 로그에 비밀값을 출력하지 않는다.
- `docs/HANDOFF.md`는 세션 전환을 위한 로컬 전용 문서다. 계정명과 운영 상태가 포함될 수 있으므로 Git에 추가·커밋·푸시하지 않는다.
- `web/data.js`는 `hotpost/report.py`가 만드는 파일이다. 프런트엔드 데이터 모델을 바꾸면 리포트 생성 코드와 화면 코드를 같이 검토한다.

## 주요 경로와 계약

- 모니터링 계정의 기준 저장소는 SQLite `managed_accounts`다. `influencer_list.txt`는 DB 최초 생성 시 한 번만 가져온다. 등록·삭제는 `hotpost/accounts.py`, 웹 API는 `hotpost/server.py`, UI는 `web/accounts.*`에 있다. 삭제해도 과거 게시물은 보존하고 다음 리포트에서만 제외한다.
- 수집·분석은 `hotpost/cli.py` → `hotpost/collectors/` → `hotpost/storage.py` → `hotpost/analyze.py` → `hotpost/report.py` 순서다. 수동 수집과 macOS LaunchAgent 수집은 `data/collect.lock`으로 중복 실행을 막는다. 일정 설치/삭제는 사용자 OS 상태를 변경하므로 명시적 요청 없이 실행하지 않는다.
- 소스 찾기는 `hotpost/source_finder.py`와 `hotpost/browser_search.py`가 담당한다. 후보를 실제로 받은 뒤 유사도와 텍스트 오버레이를 검사하여 최대 20개를 ZIP에 넣는다. 기준 Instagram 릴스는 분석용이며 ZIP에 포함하지 않는다. `manifest.json`의 원 URL·권리 상태를 유지한다.
- 대본 추출은 `hotpost/transcript.py`가 담당한다. `speech`는 실제 오디오 전사, `screen_text`는 프레임 OCR이며 둘을 같은 종류의 대사로 취급하지 않는다. API는 `POST /api/transcript-jobs`, `GET /api/transcript-jobs/{id}`, `GET /api/transcript-jobs/{id}/download?format=txt|json`이다. 서버의 작업 상태는 메모리 안에 있으므로 재시작 후 이전 작업 ID를 조회할 수 없지만 결과 파일은 `data/transcripts/`에 남는다.
- 서버는 표준 라이브러리 `ThreadingHTTPServer`, 화면은 빌드 단계 없는 HTML/CSS/JS다. 백엔드 API를 바꾸면 `web/app.js`의 모달 요청·표시·다운로드도 함께 점검한다.

## 개발·검증

- Python: `.venv/bin/python -m pytest -q`와 `.venv/bin/python -m py_compile hotpost/*.py`.
- JavaScript: `node --check web/app.js`와 `node --check web/accounts.js`.
- 화면/API: `.venv/bin/python -m hotpost serve --no-browser` 후 `http://localhost:8765/`에서 확인한다. 정적 파일을 더블클릭하면 API 작업은 되지 않는다.
- 외부 플랫폼·모델 다운로드가 필요한 통합 시험은 로컬 세션과 네트워크 상태에 따라 실패할 수 있다. 이때 테스트 실패를 재현하고 원인을 기록한다. 대본 OCR·Whisper 출력은 자동 인식이므로 예제 결과를 정답 문자열로 고정하지 않는다.

## 변경 시 지켜야 할 경계

- Instagram/플랫폼 로그인, CAPTCHA, DRM, 봇 차단을 몰래 우회하지 않는다. 로그인은 사용자가 제공한 세션을 사용한다.
- 영상 다운로드 성공은 재사용 허가를 의미하지 않는다. 원 출처와 상업 이용 권리를 결과에 남긴다.
- 전사 결과에 실제로 확인되지 않은 내레이션·장면 설명을 만들어 넣지 않는다. OCR 오타를 자동으로 음성 사실로 승격하지 않는다.
- 기존 `data/`, 쿠키, 세션, 모델, 기준 영상, 사용자의 작업 트리를 지우거나 재생성하지 않는다. 필요한 변경만 적용하고 검증한다.
