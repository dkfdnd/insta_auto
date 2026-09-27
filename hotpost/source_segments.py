"""Find a bounded relevant interval in a long download before the normal quality gate."""
from pathlib import Path
import time


def extract_relevant_segment(settings, video, meta, verifier, output, deadline):
    from .source_finder import _run, _executable
    duration = meta.get('duration') or 0
    if not 180 < duration <= settings.source_long_video_max_seconds:
        return None
    ffmpeg = _executable('ffmpeg')
    if not ffmpeg:
        return None
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    length = max(4, min(90, settings.source_segment_seconds))
    scored = []
    # Inspect several intervals across the whole recording, never just its intro.
    for i in range(8):
        if time.monotonic() >= deadline:
            break
        start = max(0, (duration - length) * i / 7)
        frames = []
        for j in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            frame = output / f'scan_{i}_{j}.jpg'
            result = _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(start + length * (j + 1) / 4),
                           '-i', str(video), '-frames:v', '1', '-vf', 'scale=480:-2', str(frame)],
                          timeout=min(30, max(1, remaining)))
            if result.returncode == 0 and frame.is_file():
                frames.append(frame)
        score = verifier.score(frames) if len(frames) == 3 else None
        if score is not None:
            scored.append((score, start))
    if not scored or max(scored)[0] < .82 or deadline - time.monotonic() < 5:
        return None
    score, start = max(scored)
    target = output / 'segment.mp4'
    result = _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(start), '-i', str(video),
                   '-t', str(length), '-map', '0:v:0', '-map', '0:a?', '-c:v', 'libx264', '-preset', 'fast',
                   '-crf', '20', '-c:a', 'aac', '-movflags', '+faststart', str(target)],
                  timeout=min(120, max(1, deadline - time.monotonic())))
    if result.returncode or not target.is_file():
        return None
    return target, {'start': round(start, 3), 'end': round(start + length, 3),
                    'original_duration': duration, 'scan_similarity': round(score, 4)}
