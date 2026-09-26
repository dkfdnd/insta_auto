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
