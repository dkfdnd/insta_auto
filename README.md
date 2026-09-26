# 🔥 오늘의 터진 게시물 (hotpost)

웹의 **모니터링 계정 관리**에서 등록한 인스타그램 인플루언서들의 최근 게시물을 모아, **각 계정의 평소 성과 대비 크게 튄 게시물**을 찾아 보여준다.

## 빠른 시작

```bash
# 1) 의존성 (최초 1회)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2) 인스타 로그인 세션 (최초 1회, 세션 만료 시 재실행)
#    크롬에서 instagram.com 에 로그인해 둔 뒤:
.venv/bin/python -m hotpost login --user 내아이디 --browser chrome
#    또는 터미널에서 비밀번호 직접 입력:
.venv/bin/python -m hotpost login --user 내아이디

# 3) 수집 + 분석 + 웹페이지 열기
./run.sh            # = python -m hotpost run --serve
```

브라우저에 http://localhost:8775 가 열린다. 서버 없이 `web/index.html` 을 더블클릭해서 열어도 된다.

## 명령

| 명령 | 설명 |
|---|---|
| `python -m hotpost run` | 수집 → 분석 → `data/report.json`, `web/data.js` 생성 |
| `python -m hotpost run --serve` | 위 작업 후 웹서버 실행 |
| `python -m hotpost run --only 계정1 계정2` | 일부 계정만 |
| `python -m hotpost run --source demo` | 샘플 데이터로 화면 확인 (별도 DB 사용, 화면은 덮어쓰므로 실데이터로 되돌리려면 `analyze`) |
| `python -m hotpost analyze` | 수집 없이 리포트만 재생성 (기준값 바꿨을 때) |
| `python -m hotpost serve` | 웹페이지만 열기 |
| `python -m hotpost sources SHORTCODE` | 릴스 장면 분석 → 공개 소스 후보 탐색·검증·ZIP 생성 |
| `python -m hotpost import dump.json` | 브라우저 덤프(`tools/browser_dump.js`) 가져오기 |
| `python -m hotpost list` | 인플루언서 목록 파싱 확인 |
| `python -m hotpost schedule install` | Windows/macOS에서 매일 오전 7시 통계·제작 자료 수집 등록 |
| `python -m hotpost schedule status` | 자동 수집 등록 상태 확인 |
| `python -m hotpost schedule uninstall` | 자동 수집 일정 제거 |

릴스 상세 모달에는 **소스 영상 찾기·다운로드**와 **대본 추출** 버튼이 있다. 두 작업 모두
`python -m hotpost serve`로 실행한 서버가 필요하므로, `web/index.html`을 파일로만 열면 동작하지 않는다.

## 인플루언서 추가

대시보드 상단 또는 계정별 요약의 **👥 모니터링 계정 관리**를 열어 아이디, `@아이디` 또는 Instagram 프로필 URL을 등록한다.
메모도 함께 저장할 수 있으며 삭제하면 다음 수집·분석부터 제외된다. 삭제해도 이미 수집한 게시물과 통계 원본은
보존되므로 계정을 다시 등록하면 이어서 사용할 수 있다.

기존 `influencer_list.txt` 목록은 계정 DB를 처음 만드는 시점에 한 번 자동으로 가져온다. 이후 SQLite가 기준
저장소가 되며, 웹에서 모든 계정을 삭제해도 텍스트 파일에서 다시 생성되지 않는다.

```
https://www.instagram.com/some_account?stkn=xxxx
@another_account | 주방 살림 위주
third_account
```

## 화면에서 기준 조절하기

카드 목록 위의 **⚙️ 판정 기준 조절** 패널에서 재수집 없이 바꿀 수 있다. 서버가 SQLite에 기준과 버전을 저장하고 리포트를 다시 계산한다.

- 등급 기준 배수 (🔥 / 🔥🔥 / 🔥🔥🔥)
- 릴스·사진 지표 가중치 (조회수 / 댓글 / 좋아요)
- 개별 지표 최소 배수 (예: 댓글이 평소 2배 이상인 것만)
- 절대 최소값 (최소 조회수·댓글·좋아요, 노이즈 컷)
- 계정 팔로워 범위, 판정 신뢰도, 신규 게시물 보정 on/off
- 프리셋: 기본 · 댓글 중심 · 조회수 중심 · 엄격 · 느슨

통계 타일, 핫 주제, 계정별 요약도 같은 기준으로 다시 계산된다. `config.json`의 판정 값은 SQLite 기준의 최초 기본값이다.

표본·후속 관측이 부족하거나 신규 보정에만 의존하면 **잠정 후보**로 표시한다.
**성과 확인**은 보정 전 배수도 기준 이상이고 같은 유형 표본이 기본 8개 이상이어야 한다.
릴스는 조회수 기준 표본도 8개 이상, 3시간 이상 간격의 성공 관측 두 번 이상, 마지막 성공 관측이
기본 30시간 이내여야 한다. 이는 계정의 평소 대비 상대 성과이며 절대적인 바이럴·전환 성과를 뜻하지 않는다.
판정 상태 필터와 상세 화면의 보정 전 배수·추가 확인 사항을 함께 확인한다.

## 판정 방식 (요약)

- 계정마다 최근 30개 게시물(같은 유형 우선)의 **중앙값** = 평소 성과
- 게시 후 72시간까지는 기준선을 35→100% 로 점진 적용 (신규 게시물 보정)
- 종합 배수 = 지표별 배수의 가중 기하평균
  - 릴스: 조회수 50% · 댓글 30% · 좋아요 20%
  - 사진/캐러셀: 좋아요 60% · 댓글 40%
- 🔥 ≥ 1.8배, 🔥🔥 ≥ 3배, 🔥🔥🔥 ≥ 5배 (`config.json` 에서 조정)
- "오늘의 핫 주제" = 핫 게시물의 해시태그·캡션 키워드를 등급 가중 합산

자세한 근거는 `docs/market_research.md`, 구현은 `hotpost/analyze.py`.

## 구조

```
influencer_list.txt      # 기존 목록 최초 마이그레이션용
config.json              # 기준값/아이디
hotpost/
  sources.py             # 목록 파서
  collectors/            # web_graphql(기본) · instaloader · dump · demo
  storage.py             # SQLite (관리 계정 / posts / snapshots → 증가 속도 계산)
  accounts.py            # 계정 등록·삭제와 레거시 목록 1회 마이그레이션
  analyze.py             # 배수 계산 · 등급 · 주제 추출
  report.py              # report.json / web/data.js
  source_finder.py       # 소스 후보 탐색·검증·ZIP
  transcript.py          # 음성 전사·화면 OCR·TXT/JSON
  server.py              # 정적 웹 + 계정/소스/대본 API
  scheduler.py           # Windows 작업 스케줄러 / macOS LaunchAgent
  cli.py
web/                     # 순수 HTML/CSS/JS (빌드 없음)
tools/browser_dump.js    # 백업 수집 경로
data/                    # DB, 세션, 모델, 다운로드, 대본 (git 제외)
```

다른 AI·개발자를 위한 작업 가이드는 [`AGENTS.md`](AGENTS.md), 대본 추출의 입력·출력 계약과
검증 방법은 [`docs/transcript_pipeline.md`](docs/transcript_pipeline.md)를 먼저 확인한다.

## 매일 자동 실행

Windows에서는 아래 명령을 사용한다. 현재 사용자 일반 권한으로 등록하며 Windows 로그인 상태에서 실행한다.
놓친 일정은 실행 가능한 시점에 재개하고 중복 실행을 막는다. 등록 시각은 PC의 로컬 시간이다.

```powershell
.\.venv\Scripts\python.exe -m hotpost schedule install --hour 7 --minute 0
.\.venv\Scripts\python.exe -m hotpost schedule status
```

macOS에서는 아래 명령을 사용한다.

```bash
.venv/bin/python -m hotpost schedule install
```

Windows 작업 스케줄러 또는 macOS LaunchAgent가 매일 오전 7시에 통계를 수집하고 리포트를 다시 만든 뒤
팔로워 대비 조회수가 높은 릴스의 대본·소스 자료를 확보한다. Windows 명령은
`.venv\Scripts\python.exe -m hotpost schedule install`이며 로그인한 세션에서 실행한다.
macOS 예약 로그는 `data/daily_collect.log`에 쌓인다. 같은 시간에 수동 통계 수집이 실행 중이면
파일 잠금으로 중복 수집을 막는다. 자세한 조건은 [공통 사용 안내](docs/PIPELINE_GUIDE.md)를 참고한다.
수집이 반복될수록 스냅샷이 쌓여 게시물별 **시간당 증가 속도**(📈 상승 중)가 표시된다.

표본이 부족한 계정은 최초 최대 31개(판정 대상 + 비교 30개)를 확보한다. 이후 최신 5개를 새로 읽고,
웹 수집기는 마지막으로 확인한 최신 게시물까지 기본 최대 60개 범위에서 수집 공백을 따라간다.
고정된 과거 게시물은 중단 기준으로 삼지 않는다. 상한을 넘긴 공백은 주의 메시지로 남긴다.
조회수는 최신 릴스 최대 5개와 기준선의 누락 조회수 최대 10개를 보강한다. 아직 핫이 아닌 최근 릴스도
마지막 조회 시도가 오래된 순서로 최대 5개를 순환 관측한다. 기존 게시물은 삭제하지 않는다. 수집이 끝나면 등급과
`web/data.js`를 다시 생성하므로 대시보드를 새로고침하면 오전 7시 결과가 반영된다.

릴스가 한 번이라도 터진 게시물로 분류되면 별도 추적 목록에 저장한다. 이후 최신 5개 게시물 밖으로 밀려나거나
등급이 내려가더라도 최초 게시 시각부터 14일째까지 매일 오전 7시에 조회수를 다시 가져와 스냅샷으로 기록한다.

## 소스 영상 찾기

`python -m hotpost serve`로 연 웹페이지에서 릴스 카드를 누른 뒤 **소스 영상 찾기·다운로드**를 누른다.
서버가 기준 릴스의 장면을 추출하고 Playwright로 Google Lens·Yandex 역이미지 검색과
TikTok·Douyin·Xiaohongshu·Bilibili 검색을 수행한다. 공개 후보를 내려받은 뒤 dHash와 OpenCLIP을 결합해
장면·제품 유사도를 계산한다. 결과 ZIP에는 영상, 후보별 미리보기, 원 URL과 권리 상태가 담긴 `manifest.json`이 들어간다.

검색 전 캡션·저장된 음성 전사·기준 프레임 OCR·Vision 라벨에서 제품 종류와 브랜드·외형·명시된 품번을 찾는다.
근거가 부족하면 OpenCLIP 상품 카탈로그로 보완한다. 제품, 브랜드 제외, 외형, 상세 리뷰, 사용 시연,
개봉 영상의 검색어를 영어·중국어·한국어로 확장한다. 검색어마다 언어와 출처를 기록하며,
현재는 규칙·사전 기반으로 사전에 없는 제품을 자유 번역하거나 모델명을 추측하지 않는다.
예를 들어 차량 도어 컵홀더는 `car door cup holder organizer`와 `车门挂式杯架 汽车收纳`로 확장된다.
TikTok에는 영어를, Douyin·Xiaohongshu에는 중국어를 우선 사용하며 Google Cloud Vision 키가 있으면
Web Entity·Best Guess Label·일반 라벨도 검색어에 합친다. 캡션 키워드는 시각 분석의 보조 검색어로 사용한다.

- 필수 도구: `ffmpeg`, `ffprobe`, `yt-dlp`, Google Chrome (PATH 또는 `/Applications`)
- Python 패키지: `playwright`, `open_clip_torch` (`requirements.txt`에 포함)
- 첫 실행: 전용 Chrome 창이 열리며 Google 사람 확인이 나오면 60초 안에 한 번 해결한다. 세션은 `data/source_browser_profile`에 보존된다.
- 선택: `GOOGLE_CLOUD_VISION_API_KEY` — 브라우저 역검색 실패 시 사용할 API 폴백
- 선택: `PEXELS_API_KEY` — 재사용 조건이 명확한 세로형 스톡 B-roll 후보를 함께 받는다.
- 설정: `source_browser_headless`, `source_browser_frames`, `source_max_candidates`, `source_max_downloads`,
  `source_max_file_mb`, `source_use_openclip`을 `config.json`에서 조절할 수 있다.

유사도 등급은 `same-scene-likely`(동일 장면 가능성), `close-match`, `topic-related`로 구분한다.
키워드만 같은 영상은 자동으로 동일 원본이라 간주하지 않는다. YouTube/TikTok/Douyin/Xiaohongshu 등 권리 상태가
`unknown-check-before-reuse`인 파일은 원 작성자의 상업적 이용 허가를 확인한 뒤 사용해야 한다. 기본값은 후보
40개를 조사하고 성공 다운로드 최대 30개를 검사해 상위 20개를 ZIP에 담는다.
실패하면 다음 후보로 보충하되 총 시도 60회와 다운로드·검증 단계 15분 예산을 적용한다.
진행 중인 검증 한 건은 예산을 넘겨 마칠 수 있다. 관련 후보의 제목에서 새 제품명·품번을 얻으면
한 차례 추가 검색으로 최대 12개 후보를 보완한다. 자세한 변경은 `docs/priority_improvements_20260924.md`를 참고한다.

상단의 **플랫폼 로그인** 버튼을 누르면 TikTok·Douyin·Xiaohongshu·YouTube 전용 로그인 탭이 열린다.
로그인을 마치고 **로그인 확인 완료**를 누르면 전용 Chrome 쿠키가 `data/source_browser_cookies.txt`에
소유자 전용 권한으로 저장되고, 다음 검색과 `yt-dlp` 다운로드에 자동으로 사용된다. 이 쿠키 파일은 결과 ZIP에
포함되지 않으며 외부에 공유하면 안 된다.

다운로드한 영상은 여러 프레임에 OCR을 적용해 자막·워터마크 반복 여부를 검사한다. 동일 장면 유사도보다
`재가공 적합도(source_score)`에서 깨끗한 화면을 더 크게 반영하며 ZIP 안에서도 다음처럼 분리한다.

- `clean_sources/`: 반복 자막과 워터마크가 거의 감지되지 않은 우선 사용 후보
- `review_needed/`: 작은 워터마크나 일부 텍스트가 있어 직접 확인할 후보
- `edited_references/`: 여러 프레임에 자막이 잡힌 다른 제작자의 편집 영상
- `unclassified/`: OCR을 실행하지 못했거나 판정 근거가 부족한 영상

OCR은 Tesseract의 `eng+kor+chi_sim`을 사용하고 없으면 저장된 EasyOCR `ko+en` 모델로 전환한다.
읽기 어려운 텍스트가 반복되면 클린으로 단정하지 않고 `unclassified`로 남긴다. 사용 가능한 모델이 없어도
다운로드는 계속한다. 자동 분류는 보조 판단이므로 제품 라벨이나 촬영 현장의 간판을 자막으로
오인할 수 있으며 최종 사용 전 미리보기 확인이 필요하다.

서버가 없는 환경에서는 `HOTPOST_SOURCE_BROWSER_HEADLESS=true`로 headless 실행이 가능하지만 Google Lens가
CAPTCHA를 요구할 수 있다. Yandex와 플랫폼 직접 검색은 독립적으로 계속 실행된다. OpenCLIP 모델은 최초 한 번
`data/models`에 다운로드되며 이후 재사용한다.

## 게시물별 자동 쇼츠 제작

`production_enabled: true`이면 기준 통과 동영상의 소스·대본을 자동으로 받고,
대본 두 버전과 VoiceBench 음성, CapCut 프로젝트 및 MP4 제작을 순서대로 진행한다.
카드에 파일 준비 상태와 소스 개수, 버전별 다운로드 링크 및 실패 단계 재시도가 표시된다.
외부 플랫폼 인증, 대본 검토, CapCut 화면 상태에 따라 중단될 수 있다.
실행 조건·결과 위치·검증 범위는 [자동 제작 문서](docs/automatic_production.md)를 참고한다.

## 릴스 대본 추출

웹 서버에서 릴스 카드를 열고 **대본 추출**을 누른다. 저장된 Instagram 게시물의 기준 영상과
로그인 세션을 사용하므로, DB에 없는 shortcode나 접근할 수 없는 영상은 실패한다. ffmpeg로 16kHz
음성을 분리하고 Apple Silicon의 `mlx-whisper` 또는 Windows의 `faster-whisper`로
시간별 대사를 전사한다. 화면 글자는 1초 간격으로
프레임을 뽑아 EasyOCR(`ko+en`)로 읽고, 실패 시 Tesseract로 대체한다. **음성**과 **화면 글자**는
서로 다른 출처로 보존하며, 보이지 않거나 들리지 않는 문구를 추정해서 만들지 않는다.

- 필수: `ffmpeg`, `ffprobe`; Python 의존성은 `requirements.txt`에 있다.
- 첫 실행 시 공개 Whisper 모델을 `data/models/`에 받는다. Windows는 CUDA FP16을
  우선 사용하고 불가하면 CPU INT8로 자동 전환한다. EasyOCR 모델도 첫 실행 시 받는다.
- 결과: `data/transcripts/<shortcode>-<작업시각>/transcript.txt`, `transcript.json`과 기준 영상. 대시보드에서도 TXT/JSON을 다운로드할 수 있다.
- 자동 전사와 OCR에는 오타가 남는다. 특히 화면 자막과 음성 대사를 합치거나 OCR을 실제 발화로 간주하지 말고 원본과 대조한다.

## 문제 해결

### Windows에서 Chrome 로그인 가져오기가 실패하는 경우

일반 Chrome 쿠키 복호화에 실패하면 프로젝트 폴더의 PowerShell에서 다음을 실행한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m hotpost login --browser dedicated
```

열린 전용 Chrome에서 수집용 계정으로 직접 로그인하고 필요한 인증을 완료한다.
프로그램은 계정 일치와 세션 인증을 확인한 뒤 세션을 저장하고 창을 닫는다.
브라우저 프로필은 `data/instagram_browser/`에 유지되고, 수집은 저장된 세션을 재사용한다.
비밀번호·인증번호를 설정 파일이나 채팅에 저장할 필요는 없다. 대기 시간은 최대 15분이며,
로그인 확인 실패·계정 불일치·창 닫기 시 기존 세션을 덮어쓰지 않는다.
브라우저 로그인 성공과 수집 API 성공은 별개이므로 이후 계정 하나로 실제 수집을 확인한다.

- `로그인이 필요합니다` / `세션 만료` → `python -m hotpost login --user 아이디 --browser chrome`
- 계정 사이에는 기본 4~9초의 무작위 간격을 두며 오류 뒤에는 20~45초 기다린다. `config.json`의
  `sleep_between_accounts`, `sleep_between_accounts_max`, `sleep_after_error_min`,
  `sleep_after_error_max`로 범위를 조절한다. 성공과 실패 모두 다음 계정 전에 대기한다.
- `429` / `feedback_required` → 몇 시간 뒤 재시도하고 위 간격을 늘린다.
- `doc_id 를 찾지 못했습니다` → 인스타 웹 구조 변경. `data/graphql_docs.json` 삭제 후 재실행. 계속 실패하면 `tools/browser_dump.js` 로 우회.
- `data/operational.log`에는 계정별 성공·실패, 처리 시간과 다음 계정 전 대기 시간이 기록된다.
  `data/instagram_diagnostics.log`에는 GraphQL 쿼리명, 문서 ID, HTTP 상태, 오류 코드, 응답 시간과
  요청 ID가 JSON 한 줄 형식으로 기록된다. 쿠키·CSRF/LSD 토큰·전체 요청 변수는 기록하지 않는다.


## 네 프로젝트 통합 제작

대시보드의 **릴스 제작 작업실**에서 자료 선택 → PersonalProject1 재가공 → 대본·변환 계획 확정 → VoiceBench 음성 → CapCut 초안까지 진행합니다. 원본 전사문으로 재가공 대본을 자동 대체하지 않습니다. Windows/macOS 예약과 새 제작 후보 기준은 [공통 사용 안내](docs/PIPELINE_GUIDE.md)를 참고하세요.
