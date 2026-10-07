# Editing adapter

`insta_auto` and `auto_capcut` remain separate processes even when their Git
repositories are later combined. `hotpost.editing_adapter.AutoCapcutAdapter`
writes a versioned request under `data/editing_jobs/<job_id>/` and invokes the
dedicated `auto_capcut` virtual environment without a shell.

The v1 request contains local source-video paths and optional semantic labels,
an optional spoken-text script, an optional voice asset, an audio profile,
optional narration tempo, and a draft name. Results are one of
`completed`, `blocked`, or `failed`. Missing voice returns the stable
`blocked / voice_required` state because the current editor uses narration
duration and word timestamps as its timeline clock.

`script_from_transcript` copies only `speech` segments into `words.txt`.
`screen_text` remains OCR evidence and is never silently converted into spoken
subtitles. All assets passed by the adapter must live under `data/`.
Final editing rejects `source_quality=unknown` and detected text overlays by
default. A Windows compatibility spike may opt into unclassified footage
explicitly, but that override is not a claim that the footage is clean or
licensed.

`hotpost.voicebench_adapter.VoiceBenchAdapter` sends the spoken script to the
separate VoiceBench HTTP API, polls the returned request ID without resubmitting,
and atomically materializes the validated WAV under the editing job directory.
It does not import VoiceBench or select its engine, reference, quality mode, or
Seed. The API key is read from `VOICEBENCH_API_KEY` or VoiceBench's ignored
`.runtime/external-api-key.txt`; it is never written into a job request or log.

VoiceBench uses `http://127.0.0.1:8765`, insta_auto uses port 8775, and
PersonalProject1 uses port 18765. The integrated flow is:

1. Send original `speech` and reference video to PersonalProject1 for rewriting.
2. Select a reviewed rewrite and transformation plan in the production UI.
3. Synthesize the selected script through VoiceBench into a versioned WAV under
   `data/productions/<production_id>/`.
4. Pass selected source videos, scene labels/ranges, script hash, and WAV to
   `AutoCapcutAdapter`.

Integrated builds use the `clean_tts` audio profile and 1.0x tempo.
Studio renders disable automatic emphasis sound effects by default. Visual
caption emphasis does not enable audio effects. The MP4 and portable draft
use narration only unless the plan explicitly enables `sound_effects.enabled`.
Old exports and caption-only revisions retain their recorded audio.
The legacy helper retains its 1.12x default. This avoids applying microphone denoise,
podcast color, vocal beautification, and +20dB gain to a clean generated WAV.

`hotpost.production.ProductionManager` persists the entire handoff, revision,
and resume state. The legacy `build_with_voicebench` helper requires an explicit
approved script and no longer falls back to original speech. Neither
VoiceBench nor auto_capcut depends on the other subsystem.

Configuration can be overridden with `HOTPOST_AUTO_CAPCUT_ROOT`,
`HOTPOST_AUTO_CAPCUT_PYTHON`, and `HOTPOST_AUTO_CAPCUT_TIMEOUT`.
VoiceBench overrides are `HOTPOST_VOICEBENCH_URL`,
`HOTPOST_VOICEBENCH_API_KEY_FILE`, `HOTPOST_VOICEBENCH_TIMEOUT`, and
`HOTPOST_VOICEBENCH_POLL_INTERVAL`.

## 2026-10-07 자막·쉼 제작 합의

신규 제작실 편집의 자막은 auto_capcut `studio_typography.default_style()`에서
Pretendard ExtraBold / 66px / 대본 문구 그대로를 적용하고 타임라인에 버전으로
보존한다. 문장이 길면 글자 축소나 요약 대신 실제 글꼴 폭을 기준으로 구절을 나눈다.
과거 완성본·스타일 없는 과거 타임라인은 이전 렌더링 계약을 유지한다.

사용자가 비교 후 승인한 `tight` 쉼 처리를 신규 제작실 편집에 기본 적용한다.
VoiceBench의 원본 복제 음성 WAV와 voice ID는 보존한다. 별도 처리 WAV를
auto_capcut 프로세스에서 만들고 원본 ASR 시간을 샘플 단위 cut-map으로
변환한 뒤 자막·장면·완성 MP4·CapCut 초안을 같은 시계로 제작한다.
배속하거나 대본을 재작성하지 않으며 들숨을 전부 제거했다고 표시하지 않는다.
타임라인의 `voice_source`는 승인한 원본 TTS, `voice`는 쉼을 줄인 편집 음성,
`pause_processing`은 변환 기록이다. 제작실 음성 듣기는 원본 TTS를 들려주고
완성 영상은 편집 음성을 사용한다. 캐시 재실행은 동일 처리 음성을 검증해
재사용한다. 과거 완성본·자막 수정은 기존 음성과 선택 상태를 유지한다.
