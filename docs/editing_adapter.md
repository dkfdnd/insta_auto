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

The default local URL is `http://127.0.0.1:8877` because insta_auto normally
uses port 8765. Start VoiceBench on 8877 before synthesis. The intended flow is:

1. Convert transcript `speech` to `words.txt`.
2. Synthesize that exact file through VoiceBench into
   `data/editing_jobs/<job_id>/voice.wav`.
3. Pass selected source videos, `words.txt`, and `voice.wav` to
   `AutoCapcutAdapter`.

VoiceBench builds use the `clean_tts` audio profile and default to a modest
1.12x pitch-preserving tempo. This avoids applying microphone denoise,
podcast color, vocal beautification, and +20dB gain to a clean generated WAV.

`build_with_voicebench` implements those three steps as the application-level
orchestrator. The orchestration layer depends on both adapters; neither
VoiceBench nor auto_capcut depends on the other subsystem.

Configuration can be overridden with `HOTPOST_AUTO_CAPCUT_ROOT`,
`HOTPOST_AUTO_CAPCUT_PYTHON`, and `HOTPOST_AUTO_CAPCUT_TIMEOUT`.
VoiceBench overrides are `HOTPOST_VOICEBENCH_URL`,
`HOTPOST_VOICEBENCH_API_KEY_FILE`, `HOTPOST_VOICEBENCH_TIMEOUT`, and
`HOTPOST_VOICEBENCH_POLL_INTERVAL`.
