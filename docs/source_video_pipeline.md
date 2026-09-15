# 소스 영상 탐색 파이프라인

## 목표와 경계

완성 릴스와 반드시 같은 원본을 찾는다고 보장하지 않는다. 릴스의 장면·제품과 유사하면서
재가공하기 좋은 **후보**를 찾고, 원 URL·권리 상태를 `manifest.json`에 남긴다.
다운로드 가능하다는 사실은 상업적 이용 허가가 아니다. 로그인·CAPTCHA는 사용자가
전용 브라우저에서 처리하며 DRM 또는 봇 차단을 우회하지 않는다.

## 현재 처리 순서

1. `data/hotpost.db`의 릴스 메타데이터와 저장된 Instagram 세션으로 기준 영상을 받는다.
2. ffmpeg로 장면 프레임을 뽑고 OpenCLIP 제품 데모 카탈로그, 선택적 Google Cloud
   Vision, 캡션을 조합해 영어·중국어 검색어를 만든다.
3. 전용 Playwright Chrome 프로필로 Google Lens·Yandex 역이미지와 TikTok·Douyin·
   Xiaohongshu·Bilibili 제품 검색을 수행한다. 웹/Bing/YouTube 검색, 로컬 후보 캐시,
   선택적 Pexels 후보도 합친다. 전용 브라우저 쿠키가 있으면 `yt-dlp`와 공유한다.
4. 중복 URL을 제거하고 기본 최대 40개 후보를 조사한다. `yt-dlp`로 최대 30개를
   임시 다운로드·검사한 뒤 실제 받을 수 있는 후보의 장면 dHash와 OpenCLIP 임베딩을
   기준 릴스와 비교한다. 장면 유사도는 dHash 55% + OpenCLIP 45%다.
5. 후보 프레임의 자막·워터마크를 OCR로 검사해 `clean-source`, `light-overlay`,
   `edited-with-text`, `unknown`으로 구분한다. 재가공 적합도(`source_score`)는
   깨끗한 화면 55% + 제품 의미 유사도 30% + 장면 dHash 15%다.
6. 이 점수로 정렬해 기본 상위 20개를 ZIP에 넣는다. `clean_sources/`,
   `review_needed/`, `edited_references/`, `unclassified/` 폴더로 유형을 구분한다.
   ZIP에는 미리보기·`manifest.json`이 있지만 분석용 기준 Instagram 릴스는 없다.

## 결과 해석

`similarity`가 0.82 이상이면 `same-scene-likely`, 0.72 이상이면 `close-match`,
그 아래는 `topic-related`다. 모두 자동 추정이며 원본 일치나 사용 권리를 보장하지
않는다. `source_quality`도 OCR 보조 판정이라 제품 포장·현장 간판을 자막으로
오인할 수 있다. 최종 선택 전 영상과 원 출처·권리 상태를 직접 확인한다.

설정 기본값은 `hotpost/config.py`, 실제 점수·ZIP 구현은 `hotpost/source_finder.py`,
브라우저 검색은 `hotpost/browser_search.py`, 텍스트 오버레이는
`hotpost/text_overlay.py`가 기준이다. 이 문서와 코드가 다르면 코드 구현을 확인하고
문서도 함께 갱신한다.
