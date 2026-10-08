# insta_auto 코드 탐색 지도

먼저 바꿀 기능의 진입점과 해당 테스트만 읽는다. 운영 데이터는 data/에 있으며 모듈 재배치와 별개로 보존한다.

| 기능 | 진입점 / 구현 | 검증 |
|---|---|---|
| 수집·랭킹·일별 선정 | cli.py → collectors/ → storage.py → analyze.py/report.py → daily_hot.py/studio_automation.py | test_daily_hot.py, test_studio_automation.py |
| 제작실 조립·집필/미디어 분리 실행 | hotpost/studio.py, studio_runtime/, studio_store.py | test_studio_runtime.py, test_studio_worker_lanes.py, test_studio_workflow.py |
| 내 촬영 영상 신규 제작 | studio_self_shot.py, writing/product_research.py, web/studio-self-shot.js | test_studio_self_shot.py, test_studio_self_shot_browser.py |
| 제작 단계·버전 | studio_workflow.py, studio_store.py, studio_sources.py | test_studio_workflow.py, test_parallel_sources.py |
| 소스 후보 수집·전체 보관 소스 검색 | source_finder.py, source_search/{models,catalog,semantic,discovery,library,budget}.py | test_source_expansion.py, test_source_discovery.py, test_source_library.py, test_source_probe_budget.py |
| 소스 검증·마스크 증거·출력 결함 구간 제외 | source_quality.py, source_functional.py, source_mask_review.py, source_overlay_review.py, source_review_withdrawals.py | test_source_quality.py, test_source_mask_review.py, test_source_overlay_review.py, test_source_review_withdrawals.py, test_parallel_sources.py |
| 긴 소스의 후보 구간 추출 | source_segments.py → source_finder.py의 일반 검증 | test_source_segments.py, test_source_video_track.py |
| 소스 수량 정책·플랫폼 실패 근거 | source_policy.py, source_outcomes.py, source_targets.py → studio_sources.py | test_source_quota_policy.py, test_tiktok_targets.py, test_parallel_sources.py |
| 검색어·접근 상태 | source_queries.py, source_planning.py, browser_search.py, search_access.py | test_daily_source_queries.py, test_browser_auth_blocks.py |
| 대본 내부 연결·음성·편집 외부 연결 | studio_adapter.py, voicebench_adapter.py, editing_adapter.py | 각 adapter 테스트 |
| 음성 없는·짧은 레퍼런스 | reference_narrative.py → studio_runtime/generation.py | test_reference_narrative.py, test_studio_workflow.py |
| Codex 단일 집필·검사·보완 | writing/RULES.md → contract.py → pipeline.py → codex_writer.py | test_internal_writing.py |
| 내장 작업 큐·과거 기록 | studio_adapter.py → writing/jobs.py; data/writing/legacy | test_studio_adapter_identity.py, test_internal_writing.py |
| 의미·복사·수치·자연스러움 | writing/checks.py, script_integrity.py, benchmark_wording.py, script_quantities.py → studio_top_pick.py | test_studio_script_checks.py, test_top_pick_claims.py |
| 기존 후보의 최신 규칙 검사 | studio_script_checks.py → StudioAdapter.review 로컬 검사 → studio_top_pick.py | test_studio_script_checks.py |
| 장면 관찰·대본별 선택 | studio_ai.describe_shots → scene_analysis.py | test_scene_analysis.py, test_studio_scene_selection.py |
| 로컬 GPU 작업 조정 | local_compute.py → VoiceBench 유휴 자원 API | test_local_compute.py, test_voicebench_adapter.py |
| 화면 HTTP | server.py, studio_http.py | test_dashboard_settings.py |
| 메인 화면 | web/app.js, web/discovery/ | hot_detection.test.cjs, dashboard 관련 테스트 |
| 제작 화면 | web/production-flow.js, web/studio/, web/post-result.js | production_flow.test.cjs, post_result.test.cjs |

## 상세 지도

- [제작 실행 모듈](studio_runtime_architecture.md)
- [프런트엔드 모듈](frontend_architecture.md)

## 안정적인 경계

`hotpost.studio.Studio`, `hotpost.source_finder.Candidate/OpenClipVerifier`는 기존 호출자를 위한 진입점을 유지한다. Git submodule이나 별도 저장소로 쪼개지 않고 저장소 내부 Python 패키지·브라우저 모듈로 책임을 나눈다. `production.py` 및 기존 제작 페이지는 저장된 작업과 실제 호출자가 있어 단순히 오래됐다는 이유로 제거하지 않는다.

기존 완성 영상·대본·음성·세션·작업 ID는 보존한다. CAPTCHA 차단과 사용자 정지 상태를 리팩토링 중 변경하지 않는다. 자동 제작의 내용 평가는 참고 의견이며 사용자 승인 대기를 새로 만들지 않는다.

장면 분석은 최대 6개 장면·24개 이미지씩 관찰한 뒤 텍스트만으로 대본별 순위를 정한다.
현재 묶음에 실제 전달된 프레임의 설명만 다음 단계에 넘기며, 설명 누락·순위 실패는
미확인 임시 배치로 표시한다. `context_only`는 핵심 동작의 증거로 승격하지 않는다.
