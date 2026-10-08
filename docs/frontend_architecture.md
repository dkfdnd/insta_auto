# 프런트엔드 코드 찾기

빌드 도구 없이 정적 HTML이 기능별 JavaScript를 순서대로 불러온다. 아래 `submodule`은
기능별 파일·폴더를 뜻하며 Git submodule이나 별도 패키지 설치가 필요하지 않다.

## 화면별 진입점

| 작업 | 먼저 읽을 파일 | 기능 모듈 |
|---|---|---|
| 게시물 목록·검색·필터 | `web/app.js` | `web/discovery/model.js`, `web/hot-detection.js` |
| 오전 수집 후 열린 화면 갱신 | `web/discovery/report-refresh.js` | `app.js`의 `refreshDashboard()` |
| 원본 소스 ZIP·대사 추출 | `web/discovery/reference-jobs.js` | 모달 하단 원본 정보에서 사용하는 독립 작업 |
| 게시물 상세의 4단계·완성본 비교 | `web/post-result.js` | `web/post-result.css` |
| 제작실 목록·작업 열기·탭 | `web/studio.js` | `web/studio-board.js`, `web/studio-intake.js` |
| 제작 요청·입력 보존·버전 선택 | `web/production-flow.js` | `web/studio-detail.js`, `web/studio-workspace.js` |
| 제작실 소스 현황·검색 기록·선택 | `web/studio/source-view.js` | `web/source-upload.js` |
| 자막·타이밍·장면 편집 | `web/caption-editor.js` | `web/caption-editor.css` |
| 목소리 선택 | `web/voice-picker.js` | 자동 제작의 기본 목소리는 백엔드·VoiceBench 계약을 따른다 |
| 설정·로그인·알림 | `web/settings.js`, `web/platform-logins.js` | `web/display-settings.js`, `web/notices.js`, `web/collection-notifications.js` |

## 경계와 불변 조건

- **발견 시각:** `hot-detection.js`가 한국 날짜·최근 N시간·오늘 우선 정렬을 정의한다.
  `discovery/model.js`는 같은 규칙으로 필터·주제·상단 통계를 계산한다. 업로드 시각과 섞지 않는다.
- **보고서 갱신:** 페이지 포커스·다시 표시·60초마다 `GET /api/report`를 확인한다.
  판정 기준 버전이 같아도 새 수집 시각이면 반영한다. 페이지 이동이나 상세 모달 재생성 없이
  목록과 통계만 갱신하므로 열린 영상·입력이 보존된다. 조회 실패 때는 마지막 확인 결과를 유지한다.
- **소스 선택:** `studio/source-view.js`의 `selection()`이 체크박스와 변경 여부 비교의 공통 기준이다.
  현재 완성본의 사용 소스와 다음 제작에 저장한 선택을 구분하며, 빈 선택도 유효한 선택으로 보존한다.
- **API 쓰기:** 소스 뷰는 화면·선택 기준만 담당한다. 실제 제작 요청과 저장은
  `production-flow.js`에서 수행한다. `discovery/reference-jobs.js`는 원본 추출 전용 API만 사용한다.
- **기존 작업:** `production.html` 및 `studio.js`의 이전 프로토콜 처리는 저장된 과거 작업의
  호환 경로다. 최신 화면에서 쓰지 않는다는 이유만으로 삭제하지 않는다. 일반 설정의 제작실 링크는 `studio.html`이다.
- **재생·표시:** 상세 4단계, 원본 왼쪽/완성본 오른쪽, 이전 완성본, 실제 실행 작업만 스피너 표시,
  완료 녹색·대기 회색·실패 빨간색 계약을 유지한다. 명시적 테마 선택이 OS 테마보다 우선한다.

## 로딩 순서

`index.html`과 `studio.html`은 `studio/source-view.js`를 `production-flow.js`보다 먼저 불러온다.
`index.html`은 `hot-detection.js`, `discovery/model.js`, `discovery/report-refresh.js`,
`discovery/reference-jobs.js`를 `app.js`보다 먼저 불러온다. 독립 VM 테스트도 같은 의존 순서를 지켜야 한다.
기존 최상위 파일 URL·공개 `window.ProductionFlow`, `window.PostResult` 인터페이스는 유지한다.

## 검증

```powershell
node --test tests/*.test.cjs
Get-ChildItem web -Recurse -Filter *.js | Where-Object Name -ne data.js |
  ForEach-Object { node --check $_.FullName }
.\.venv\Scripts\python.exe -m pytest -q tests/test_dashboard_browser.py tests/test_production_flow_browser.py tests/test_studio_board_browser.py
```

DOM 회귀 테스트는 `linkedom`을 사용한다. 설치된 경로를 `HOTPOST_TEST_DOM`에 지정할 수 있으며,
미설치 상태에서 건너뛴 DOM 테스트를 화면 검증 성공으로 보고하지 않는다.
브라우저 테스트는 격리된 fixture API를 사용하며 실제 수집·영상 제작을 요청하지 않는다.
`web/data.js`는 생성 결과이므로 수동으로 수정하지 않는다.
