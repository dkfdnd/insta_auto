# 시장조사: 인스타그램 '터진 게시물' 데이터를 어떻게 얻을 것인가 (2026-09)

## 1. 왜 어려운가
- 인스타그램은 검색/탐색 API 를 외부에 열지 않는다. 공식 Graph API 는 **본인 비즈니스 계정**의 인사이트만 준다.
  (Business Discovery 로 타 비즈니스/크리에이터 계정의 좋아요·댓글 수는 볼 수 있지만 **조회수는 불가**, 앱 심사 필요)
- 비로그인 상태의 웹 엔드포인트(`web_profile_info`, `?__a=1`)는 2023년 이후 사실상 전부 401/로그인 요구.
- 로그인 상태라도 `api/v1/users/web_profile_info` 는 요청이 조금만 몰리면 `429` / `feedback_required` 로 막힌다 (이번 실험에서 재현됨).

## 2. 후보 비교

| 방식 | 조회수 | 좋아요/댓글 | 비용 | 안정성 | 판단 |
|---|---|---|---|---|---|
| 공식 Graph API (Business Discovery) | ✗ | ○ | 무료, 앱 심사 | 높음 | 조회수 없음 → 릴스 분석에 부적합 |
| 유료 스크래핑 API (Apify, RapidAPI 계열) | ○ | ○ | 월 $30~200 | 중 | 나중에 규모 커지면 고려 |
| instaloader (오픈소스) | △ | ○ | 무료 | 낮음 (web_profile_info 의존 → 차단 잦음) | 보조 수집기로만 유지 |
| **웹사이트 GraphQL 직접 호출** (사이트가 쓰는 것과 동일) | ○ (media info 보강) | ○ | 무료 | 중 (doc_id 변경 시 재탐색 필요) | **채택** |
| 브라우저 콘솔 덤프 (JS) | ○ | ○ | 무료 | 중 | 백업 경로 (`tools/browser_dump.js`) |

## 3. 채택한 구조
1. 크롬에 로그인된 쿠키를 한 번 가져와 세션 파일로 저장 (`hotpost login --browser chrome`).
2. 프로필 페이지 HTML 에서 LSD / fb_dtsg 토큰을 읽고, 웹 번들에서 GraphQL `doc_id` 를 자동 탐색해 캐시.
3. `PolarisProfilePostsQuery` 로 타임라인(좋아요·댓글·캡션·썸네일), `PolarisProfilePageContentQuery` 로 팔로워 수,
   릴스 조회수는 `api/v1/media/{id}/info` 로 보강.
4. 실험으로 확인한 함정
   - 로그인 상태여도 GraphQL 의 `av`/`__user` 는 `0` 이어야 한다 (viewer id 를 넣으면 1357001 "로그인 필요").
   - User-Agent 가 쿠키를 만든 브라우저와 크게 다르면 1357054 "요청이 처리되지 않았습니다".
   - `PolarisProfileReelsTabContentQuery` 는 필수 변수 규격을 못 찾아 미사용 (missing_required_variable_value).

## 4. '터진 게시물' 정의 (경쟁 도구들의 공통 관행 + 우리 상황)
- Social Blade / HypeAuditor / Notjustanalytics 류는 **계정 평균 대비 배수**와 **참여율(ER)** 을 기본 지표로 쓴다.
- 우리는 계정 규모가 제각각인 리스트를 보므로 절대 수치 대신 **계정 자체 중앙값 대비 배수**를 채택했다.
  평균 대신 중앙값을 쓰는 이유: 한두 개의 초대박 게시물이 기준선을 끌어올려 나머지를 전부 '평범'으로 만드는 것을 막기 위해.
- 댓글은 별도 가중치(릴스 30%, 사진 40%)를 준다. 댓글이 튀는 게시물은 "따라 하고 싶은 주제"일 확률이 높다.
- 게시 후 72시간까지는 반응이 덜 쌓였으므로 기준선을 35%→100% 로 점진 적용한다(신규 게시물 보정).

## 5. 운영 리스크
- 인스타그램 약관상 자동 수집은 회색지대. 개인 계정으로 **하루 1~2회, 계정당 수십 요청** 수준으로 유지하고 요청 간 지연을 둔다.
- doc_id 변경 → 자동 재탐색. 완전히 막히면 `tools/browser_dump.js` → `hotpost import` 로 우회.
- 세션 만료 시 `hotpost login --browser chrome` 재실행.
