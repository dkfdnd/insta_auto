# 릴스 대본 추출 파이프라인

## 입력과 실행 조건

릴스 상세 모달의 **대본 추출** 버튼은 `POST /api/transcript-jobs`에
`{"shortcode":"Dcp3P-WyMFe"}` 형태로 요청한다. `hotpost/server.py`는 작업 ID를 반환하고,
`web/app.js`는 상태를 polling한다. 대상 shortcode는 `data/hotpost.db`의 `posts`에 있고
`media_id`가 있어야 한다. `hotpost/source_finder.py`의 `_post`와 `_download_reference`를
재사용해 저장된 Instagram 세션으로 기준 릴스를 받는다. 접근 불가·세션 만료라면 실패한다.

## 분석 순서

1. `ffprobe`로 실제 영상 길이를 읽고 `ffmpeg`로 16kHz 모노 WAV를 만든다.
2. Apple Silicon은 `mlx-whisper`와 `Settings.transcript_model`을, Windows는
   `faster-whisper`와 `Settings.transcript_faster_whisper_model`을 사용해 실제
   오디오를 시간 구간별로 전사한다. Windows에서는 먼저 CUDA FP16을
   시도하고 실행할 수 없으면 CPU INT8로 전환한다.
3. 별도로 `ffmpeg`가 기본 1fps(`Settings.transcript_ocr_fps`)로 화면 프레임을 만든다.
   EasyOCR `ko+en` 모델로 읽고 화면 가장자리의 광고 표시·워터마크와 낮은 신뢰도의
   문자 조각을 제한한다. EasyOCR를 실행할 수 없으면 Tesseract로 대체한다.
4. 연속 프레임의 같은 문구는 하나의 구간으로 합치고, 음성과 OCR 문구를 시간순으로
   정렬한다. 두 출처는 끝까지 별도로 보존한다.

## 결과 계약

`data/transcripts/<shortcode>-<timestamp>/` 아래에 `reference.mp4`, `audio.wav`,
`ocr_frames/`, `transcript.json`, `transcript.txt`를 남긴다. JSON의 `speech`와
`screen_text` 배열은 각각 `{source,start,end,text}` 구간이며, `lines`는 둘의 시간순
결합이다. `notes`에는 자동 인식의 한계와 백엔드 실패가 기록된다. 서버는 공개 상태
응답에서 내부 파일 경로를 숨기고 TXT/JSON 다운로드 URL만 제공한다. 작업 상태는
프로세스 메모리에 있어 서버를 재시작하면 ID는 사라지지만 로컬 결과 파일은 남는다.

## 정확도와 검증

이 파이프라인은 실제 음성·화면 글자만 추출한다. Whisper의 고유명사·배경음 오인식과
OCR의 한글 받침 오타가 남을 수 있다. OCR 문구가 영상에서 보였다는 사실만으로
발화한 대사라고 단정하지 않는다. 제작용 최종 대본은 원본과 대조해 사람이 수정한다.

`tests/test_basic.py`는 OCR 연속 구간 병합과 워터마크 위치 필터를 검사한다.
실제 통합 시험에서는 릴스 상세 버튼 또는 API로 작업을 시작해 `done` 상태,
음성/화면 구간, TXT·JSON HTTP 200 다운로드를 확인한다. 네트워크·Instagram 세션과
모델 파일이 필요하고 첫 실행은 다운로드 때문에 느릴 수 있다. 모델 출력 문자열을
테스트의 고정 정답으로 사용하지 않는다.
