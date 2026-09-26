# 마스킹·썸네일 모듈 (2026-09-24)

## 책임과 경계

| 모듈 | 입력 → 출력 | 수정 지점 |
|---|---|---|
| `hotpost.thumbnail_planner` | 주제·대본·검토 근거 → 후보/선택 문구·이미지 브리프 | 후킹 전략·문구·구도 |
| `hotpost.flow_image_adapter` | 브리프·참조 이미지 → 대기 작업 / 검토한 Flow 이미지 | 생성 서비스 및 전달 방식 |
| `hotpost.thumbnail_jobs` | prepare / accept / export CLI | 운영 인터페이스 |
| `hotpost.editing_adapter` | 음성·영상·썸네일·마스크 → JSON 작업 | 오케스트레이션 |
| auto_capcut `core.watermark_masks` | 원본 시간 구간·검토한 사각형 → 편집 가능한 흐리게 트랙 | 마스크 적용 |
| auto_capcut `core.cover` | 이미지·한 줄 문구 → 첫 1프레임 영상/텍스트 | 썸네일 스타일 |

두 저장소 간 직접 import, VoiceBench 엔진 수정, 대본/TTS 재생성을 하지 않는다.
기존 요청은 계약 1.0을 유지하고, 시각 모듈을 쓰는 요청만 1.1로 올린다.
구버전 runner는 1.1을 거부하므로 썸네일·마스크를 무시한 채 성공할 수 없다.
신규 기능은 Python 어댑터/CLI 경계이며, 기존 웹 편집 UI에 버튼을 추가한 것은 아니다.

## 후킹 문구

- '심리학의 7요소'는 단일한 표준 분류로 가정하지 않는다. 현재 편집 전략은
  호기심 / 손실 회피 / 대조 / 구체성 / 자기 관련성 / 사회적 증거 / 희소성이다.
- 한 문구에 7개를 모두 섞지 않는다. 주 전략 1개를 선택하고 선택 근거를 보존한다.
- 기본 후보는 보수적인 템플릿이다. 에이전트/편집자는 `custom_hook`으로 문구를
  개선할 수 있다. `script_quote`는 추적 가능한 관련 근거일 뿐 사실 증명은 아니다.
- 사회적 증거와 희소성은 별도 검토한 `claims`의 출처와 근거가 없으면 후보 제외.
  대본에 '품절'이 있다고 실재고가 검증된 것은 아니다. 실제 품절·재입고 주장은
  최신 판매자 자료 등 별도 확인이 필요하다.
- 출력은 줄바꿈 없는 20자 이내. 문구 검토를 통과해야 편집에 전달한다.
  썸네일 문구는 `words.txt`에 넣지 않으며 TTS로 읽지 않는다.

## Flow 실행 및 재개

공식 기능은 [Flow 이미지 생성 안내](https://support.google.com/flow/answer/16729550?hl=en)를
기준으로 한다. 프롬프트와 참조 이미지를 넣고 이미지 1개, 세로 9:16을 생성한다.
요청한 서비스는 Google Flow이며 Gemini 유료 API/다른 생성기로 임의 전환하지 않는다.
비공개 endpoint, 쿠키 추출, CAPTCHA 우회는 사용하지 않는다.

브라우저 연결이 있으면 에이전트가 **새 전용 프로젝트**에서 UI를 조작한다.
이것은 현재 대화의 브라우저 도구를 사용하는 assisted 자동화이며, 서버가 무인으로
Chrome을 제어하는 상시 worker는 아니다. 연결·로그인·업로드 권한이 없으면 동일한
`request.json`/`prompt.txt`를 이용한 수동 방식으로 재개한다. 브라우저 연결만 된 상태나
생성 버튼을 누른 상태를 `completed`로 기록하지 않는다.

2026-09-24 실행 결과: 사용자가 Chrome 확장의 파일 URL 접근을 직접 허용한 후,
승인된 참조 1장 업로드 → Flow 이미지 생성 → 원본 다운로드 → 검토/수령을 완료했다.
권한 설정은 에이전트가 변경하지 않는다. 이 성공은 현재 로그인된 브라우저의 assisted
실행 검증이며 서버 무인 실행을 뜻하지 않는다. 제품 세부 형상은 생성 과정에서 달라질
수 있으므로 상업 게시 전 실물과 비교해야 한다.

```powershell
# brief.json: subject, script, feature/preferred/custom_hook/claims(선택)
.venv\Scripts\python.exe -m hotpost.thumbnail_jobs --data-root data --job-dir data/editing_jobs/example-flow prepare --brief data/brief.json --reference data/reference.png
# 다운로드 이미지도 data 아래에 둔다. --reviewed는 실제 제품/문구 검토 후만 사용.
.venv\Scripts\python.exe -m hotpost.thumbnail_jobs --data-root data --job-dir data/editing_jobs/example-flow accept --image data/flow.png --flow-url https://flow.google.com/project/PROJECT_ID --reviewed
.venv\Scripts\python.exe -m hotpost.thumbnail_jobs --data-root data --job-dir data/editing_jobs/example-flow export
```

export 출력은 `AutoCapcutAdapter.build(thumbnail=...)`에 전달한다.
`GoogleFlowImageAdapter.editing_thumbnail(job_dir)`도 같은 dict를 반환한다.
이미 사람이 편집한 프로젝트는 전체 빌드를 다시 돌리지 않고 `auto_capcut.revise_cover`
CLI에 명시적인 원본 draft JSON과 썸네일 계약을 전달해 새 이름으로 복제할 수 있다.
기존 첫 1프레임만 교체하며 나머지 컷·음성·자막·효과 타이밍을 보존한다.
이미지 미수령은 `thumbnail_image_pending`; 참조/요청/수령 이미지 변경은 재검토다.
Flow URL은 운영자가 기록한 출처이며 실제 생성 서비스를 암호학적으로 증명하지 않는다.

## 시각 품질과 한계

- 2026-09-24 피드백: `명품인 줄?\n이 백팩의 반전`처럼 두 줄을 명시한다.
  첫 줄 흰색, 둘째 줄만 강조색이며 한 줄 전체 강조는 기존 계약 호환용이다.
- `create_plan(visual_direction={desire, scene, composition}, caption_placement="top")`
  으로 욕구·장면·구도를 상품별로 지정한다. 기존의 차분한 상품 정물을 그대로
  반복하지 않는다. 사람이 필요한 상품인지도 개별 판단한다.
- 후킹 품질 기준: 작은 화면에서 제품 식별, 갖고 싶은 결과/해결할 문제,
  한눈에 들어오는 대비, 문구와 장면의 연결. 이것은 편집 검토 기준이며 CTR 보장이 아니다.
- 제품 외형·색·재질·기존 로고 보존이 우선. 그럴듯한 다른 제품이면 재생성한다.
- 이미지에는 한글 문구를 생성하지 않는다. CapCut 텍스트 레이어로 분리한다.
- 첫 1프레임 삽입은 편집 규칙일 뿐 게시 플랫폼의 대표 커버 선택을 보장하지 않는다.
- 흐리게는 픽셀을 가리는 효과이지 원본 복원/저작권 정리/출처 삭제가 아니다.
  원본·출처·권리 메타데이터를 유지한다. 움직이는 워터마크는 구간별 추가 검토가 필요하다.
- 자동 검출·추적은 이번 모듈에 포함하지 않았다. 주석 없는 원본 구간은 그대로 남는다.
- 이미지/문구/마스크의 구조 테스트와 실제 CapCut 재생 검토는 별개다.
