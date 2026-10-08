# Studio 런타임 코드 지도

외부 진입점은 계속 `from hotpost.studio import Studio`다. HTTP 경로, DB 상태 형식,
작업 ID, 체크포인트, 기존 영상 경로는 변경하지 않았다. `studio.py`는 작업 디렉터리,
DB, 프로세스 잠금 및 워커 소유권을 초기화하고 아래 책임을 조립한다.

| 변경하려는 동작 | 먼저 읽을 파일 |
| --- | --- |
| 사용자 저장·재시도·재개 명령 | `hotpost/studio_runtime/commands.py` |
| 제작실 JSON·재생 주소·미디어 접근 범위 | `hotpost/studio_runtime/media.py` |
| 작업 실행 루프·결과 저장·구형 자동 제작 | `hotpost/studio_runtime/lifecycle.py` |
| 원본 준비·추가 검색·대본·VoiceBench 음성 실행 | `hotpost/studio_runtime/generation.py` |
| CapCut 별도 프로세스·편집·수정·등록 실행 | `hotpost/studio_runtime/editing.py` |
| 선택 버전 조회·파일 해시 | `hotpost/studio_runtime/common.py` |
| 현재 자동 제작 단계·피드백·완성본 이력 | `hotpost/studio_workflow.py` |
| 최소 소스 수량·병렬 수집·검색 재개 | `hotpost/studio_sources.py` |
| SQLite 트랜잭션·큐·복구 | `hotpost/studio_store.py` |
| 로컬 대본·영상 검토·음성의 GPU 작업 직렬화 | `hotpost/local_compute.py` |

## 유지해야 하는 경계

- HTTP는 `Studio.action()` / `Studio.public()` / `Studio.media()`를 사용한다.
- 단계 실행은 `self._<작업종류>()`, 완료는 `self._accept()`로 호출한다. 하위 클래스나
  테스트가 개별 실행 단계를 교체할 수 있으며, 믹스인 구현을 직접 호출하지 않는다.
- 장기 HTTP·렌더링은 상태 변경 트랜잭션 밖에서 실행한다. `check-script`와
  `prepare-caption-preview`는 명령 진입점에서 별도로 처리한다.
- 소스·미디어 제작·Codex 대본 세 워커와 렌더 잠금, 파일 기반 작업 소유권을 보존한다. 모듈 import는
  워커를 시작하거나 운영 DB를 열지 않는다.

Codex 집필은 `scripts`(rewrite/proposal) 워커, 원본 준비·음성·편집·등록·출력은
`media` 워커가 담당한다. 로컬 미디어/모델 작업과 렌더는 여전히 한 제작 워커에서
실행한다. 긴 음성/렌더링이 다른 게시물의 집필까지 막지 않는다. `claim('production')`은
기존 호출자를 위한 전체 제작 단계 조회를 유지한다. DB 트랜잭션은 같은 게시물의
상태를 바꾸는 제작 작업 하나만 실행하도록 제한하며, 별도 소스 수집과 적용 전
대본 수정안은 병행할 수 있다. 내부 Codex CLI 집필 큐의 단일 OS 워커는 유지한다.
- `digest`, `selected`는 기존 호출자를 위해 `hotpost.studio`에서 재노출한다.
- 구형 자동 제작과 수동 승인 경로는 실제 저장 데이터·호출자·회귀 테스트가 있으므로
  죽은 코드로 간주해 제거하지 않는다. 새 기능은 가능하면 현재 workflow 경로에 추가한다.

## 검증 범위

`tests/test_studio_runtime.py`는 명령 검사 중 워커 진행, UI용 상태의 복사,
재생 주소의 작업 범위, 단계/완료 오버라이드를 확인한다. 기존 `test_studio*`,
`test_parallel_sources.py`, `test_source_expansion.py`는 승인·재개·재시도·복제 음성·
자막·미디어·완성 이력 및 별도 서비스 경계를 함께 검증한다.

리팩토링은 동작 변경과 분리한다. 소스 기준이나 대본 정책을 바꿀 때에는 위 대응
파일과 계약 테스트만 읽으면 되며, 전체 제작 코드를 매번 읽을 필요는 없다.

## 로컬 모델 자원 조정

`_rewrite`, `_voice`, `StudioAdapter.editorial`은 재진입 가능한 프로세스 내 잠금을
공유한다. 대본 작업 안에서 editorial을 호출해도 중복 잠금으로 멈추지 않는다.
대본/시각 검토 시작 전과 성공한 음성 저장 직후에는 인증된 VoiceBench HTTP
`POST /v1/resources/release-idle`로 유휴 모델 해제를 요청한다. 음성 작업이 있으면
서버가 해제를 거절하며 대본은 기존 `studio_timeout` 한도 안에서 기다린다.
성공한 음성 뒤의 선택적 정리 실패는 저장된 음성을 실패로 바꾸지 않는다.

VoiceBench의 엔진·참조·목소리 선택은 기존 서버 정책을 유지한다. Hotpost는 다른
프로젝트를 import하거나 프로세스를 강제 종료하지 않는다. 구버전 API 404/405/501,
서비스 미연결은 호환성을 위해 건너뛰며 원격 서비스 자원은 조정하지 않는다.
독립된 외부 클라이언트나 다른 Hotpost 프로세스까지 잠그는 분산 GPU 예약은 아니다.
