# 🔥 오늘의 터진 게시물 (hotpost)

`influencer_list.txt` 에 적힌 인스타그램 인플루언서들의 최근 게시물을 모아, **각 계정의 평소 성과 대비 크게 튄 게시물**을 찾아 웹페이지로 보여준다.

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

브라우저에 http://localhost:8765 가 열린다. 서버 없이 `web/index.html` 을 더블클릭해서 열어도 된다.

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

## 인플루언서 추가

`influencer_list.txt` 에 한 줄씩 추가하면 끝. URL(`?stkn=` 붙은 공유 링크 포함), `@아이디`, 아이디만 적어도 된다. `#` 으로 시작하는 줄은 주석, `|` 뒤는 메모.

```
https://www.instagram.com/some_account?stkn=xxxx
@another_account | 주방 살림 위주
third_account
```

## 화면에서 기준 조절하기

카드 목록 위의 **⚙️ 판정 기준 조절** 패널에서 재수집 없이 즉시 바꿀 수 있다 (브라우저에 저장됨).

- 등급 기준 배수 (🔥 / 🔥🔥 / 🔥🔥🔥)
- 릴스·사진 지표 가중치 (조회수 / 댓글 / 좋아요)
- 개별 지표 최소 배수 (예: 댓글이 평소 2배 이상인 것만)
- 절대 최소값 (최소 조회수·댓글·좋아요, 노이즈 컷)
- 계정 팔로워 범위, 판정 신뢰도, 신규 게시물 보정 on/off
- 프리셋: 기본 · 댓글 중심 · 조회수 중심 · 엄격 · 느슨

통계 타일, 핫 주제, 계정별 요약도 같은 기준으로 같이 다시 계산된다. `config.json` 의 값은 `run`/`analyze` 시 기본값으로만 쓰인다.

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
influencer_list.txt      # 입력 목록
config.json              # 기준값/아이디
hotpost/
  sources.py             # 목록 파서
  collectors/            # web_graphql(기본) · instaloader · dump · demo
  storage.py             # SQLite (posts / snapshots → 증가 속도 계산)
  analyze.py             # 배수 계산 · 등급 · 주제 추출
  report.py              # report.json / web/data.js
  cli.py
web/                     # 순수 HTML/CSS/JS (빌드 없음)
tools/browser_dump.js    # 백업 수집 경로
data/                    # DB, 세션, 리포트 (git 제외)
```

## 매일 자동 실행 (선택)

```bash
crontab -e
# 매일 오전 8시, 오후 8시
0 8,20 * * * cd /Users/dkfdnd/dev/insta_auto && .venv/bin/python -m hotpost run >> data/cron.log 2>&1
```

수집이 반복될수록 스냅샷이 쌓여 게시물별 **시간당 증가 속도**(📈 상승 중)가 표시된다.

## 소스 영상 찾기

`python -m hotpost serve`로 연 웹페이지에서 릴스 카드를 누른 뒤 **소스 영상 찾기·다운로드**를 누른다.
서버가 기준 릴스의 장면을 추출하고 Playwright로 Google Lens·Yandex 역이미지 검색과
TikTok·Douyin·Xiaohongshu·Bilibili 검색을 수행한다. 공개 후보를 내려받은 뒤 dHash와 OpenCLIP을 결합해
장면·제품 유사도를 계산한다. 결과 ZIP에는 영상, 후보별 미리보기, 원 URL과 권리 상태가 담긴 `manifest.json`이 들어간다.

검색 전 OpenCLIP이 기준 장면을 상품 데모 카탈로그와 비교해 영상 속 제품의 영어·중국어 검색어를 만든다.
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
40개를 조사하고 최대 30개를 임시 검증한 뒤, 재가공 적합도가 높은 영상 20개를 ZIP에 담는다.

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

OCR은 Tesseract의 `eng+kor+chi_sim` 언어 데이터를 사용한다. Tesseract나 언어 데이터가 없으면 다운로드를
중단하지 않고 `unclassified`로 표시한다. 자동 분류는 보조 판단이므로 제품 라벨이나 촬영 현장의 간판을 자막으로
오인할 수 있으며 최종 사용 전 미리보기 확인이 필요하다.

서버가 없는 환경에서는 `HOTPOST_SOURCE_BROWSER_HEADLESS=true`로 headless 실행이 가능하지만 Google Lens가
CAPTCHA를 요구할 수 있다. Yandex와 플랫폼 직접 검색은 독립적으로 계속 실행된다. OpenCLIP 모델은 최초 한 번
`data/models`에 다운로드되며 이후 재사용한다.

## 문제 해결

- `로그인이 필요합니다` / `세션 만료` → `python -m hotpost login --user 아이디 --browser chrome`
- `429` / `feedback_required` → 몇 시간 뒤 재시도. `config.json` 의 `sleep_between_accounts` 를 늘린다.
- `doc_id 를 찾지 못했습니다` → 인스타 웹 구조 변경. `data/graphql_docs.json` 삭제 후 재실행. 계속 실패하면 `tools/browser_dump.js` 로 우회.
