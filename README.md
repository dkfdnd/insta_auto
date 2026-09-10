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

## 문제 해결

- `로그인이 필요합니다` / `세션 만료` → `python -m hotpost login --user 아이디 --browser chrome`
- `429` / `feedback_required` → 몇 시간 뒤 재시도. `config.json` 의 `sleep_between_accounts` 를 늘린다.
- `doc_id 를 찾지 못했습니다` → 인스타 웹 구조 변경. `data/graphql_docs.json` 삭제 후 재실행. 계속 실패하면 `tools/browser_dump.js` 로 우회.
