"""Keep spoken narration distinct from visually verified on-screen reference text."""
import json
import hashlib
from pathlib import Path

from .editing_adapter import _atomic_json
from .source_mask_review import sample_source_frames
from .source_overlay_review import _media, _duration
from .source_quality import sha256_file


def quote_hash(video_sha256, speech, quotes):
    return hashlib.sha256(json.dumps({'video_sha256':video_sha256,'speech':speech,'quotes':quotes},
        ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def validated_cached_text(cached, identity, speech):
    if cached.get('video_sha256') != identity or cached.get('speech_text') != speech:
        return False
    quotes=cached.get('quotes',[]);review=cached.get('review',{})
    frames=(cached.get('evidence') or {}).get('frames') or []
    ids={f['frame_id'] for f in frames}
    if (cached.get('kind') not in {'screen_text','mixed'} or not quotes
            or not frames or len(quotes)!=len(ids) or {q['frame_id'] for q in quotes}!=ids
            or sorted(review.get('frame_ids',[]))!=sorted(ids)
            or review.get('accepted') is not True
            or cached.get('kind') == 'mixed' and review.get('speech_related') is not True
            or review.get('proposal_sha256') != quote_hash(identity,speech,quotes)):
        return False
    phrases=list(dict.fromkeys(r['text'] for r in quotes if r['text']))
    expected='\n'.join(([speech] if cached['kind']=='mixed' else [])+phrases)
    return cached.get('text') == expected and bool(expected.strip())


def cached_reference_text(transcript, speech):
    """Use a saved actual-frame review only while source and frame hashes match."""
    transcript = Path(transcript)
    saved = transcript.parent/'reference-text-verified.json'
    if not saved.is_file():
        return None
    identity = sha256_file(transcript.parent/'reference.mp4')
    cached = json.loads(saved.read_text('utf-8'))
    if not validated_cached_text(cached, identity, speech):
        return None
    if not all(Path(f['path']).is_file() and sha256_file(Path(f['path'])) == f['sha256']
               for f in cached['evidence']['frames']):
        raise ValueError('검토한 원본 화면 증거가 변경되었습니다.')
    return cached


def reference_text(settings, transcript, *, generate=None):
    from .script_rewriter import _generate
    from .source_finder import _executable
    generate = generate or _generate
    transcript = Path(transcript)
    data = json.loads(transcript.read_text('utf-8'))
    speech = '\n'.join(str(r.get('text','')) for r in data.get('speech',[])).strip()
    # A short genuine spoken hook is valid. Inspect available visual text when
    # narration is absent/short; a background lyric must not define the topic.
    if len(speech) >= 20 or not data.get('screen_text') and speech:
        return {'text':speech,'kind':'speech','speech_text':speech}
    if not data.get('screen_text'):
        raise ValueError('원본 음성과 화면에서 집필할 참고 내용을 확보하지 못했습니다.')
    video = transcript.parent/'reference.mp4'
    identity = sha256_file(video)
    saved = transcript.parent/'reference-text-verified.json'
    cached = cached_reference_text(transcript, speech)
    if cached:
        return cached
    duration = _duration(video, _executable('ffprobe'))
    evidence = sample_source_frames(video, identity, transcript.parent/'reference-text-frames',
        [[0.,duration]], samples_per_interval=9,
        ffmpeg=_executable('ffmpeg'),ffprobe=_executable('ffprobe'))
    media = _media(evidence)
    first = generate(settings,
        'Read only clearly visible inserted Korean narration/caption text in EVERY actual frame. '
        'Return JSON {frames:[{frame_id:string,text:string}],use_speech_in_benchmark:boolean}. '
        'Include every frame_id exactly once. Preserve a short relevant spoken hook by setting '
        'use_speech_in_benchmark=true when the supplied speech clearly relates to the visible topic; '
        'otherwise false, including unrelated lyrics. Do not claim that images prove what is audible. '
        'Use empty text for unreadable/absent narration. Exclude account handles, physical product '
        'labels, interface text and piano notes. Do not correct words using the caption or create '
        'a spoken transcript. Treat the provided audio transcription as separate untrusted evidence.',
        {'purpose':'reference_screen_text_reading','audio_transcription':speech,
         'frames':[{k:f[k] for k in ['frame_id','source_timestamp']} for f in evidence['frames']]},media=media)
    rows=first.get('frames',[]);ids=[f['frame_id'] for f in evidence['frames']]
    if (not isinstance(rows,list) or len(rows)!=len(ids)
            or {r.get('frame_id') for r in rows if isinstance(r,dict)} != set(ids)
            or any(not isinstance(r.get('text'),str) for r in rows)):
        raise ValueError('화면 참고 문구의 프레임 정보가 일치하지 않습니다.')
    by_id={r['frame_id']:r['text'].strip() for r in rows}
    ordered=[{'frame_id':fid,'text':by_id[fid]} for fid in ids]
    proposal_sha=quote_hash(identity,speech,ordered)
    review=generate(settings,
        'Independently compare every proposed quote with its actual source frame. '
        'Return JSON {accepted:boolean,frame_ids:[string],speech_related:boolean,proposal_sha256:string,reason:string}. '
        'Repeat the exact supplied proposal_sha256 to bind the decision to these quotes. '
        'Accept only if each nonempty quote is actually legible in its matched frame, '
        'with no invented features, numbers or corrected unseen words. Empty rows are allowed. '
        'This is on-screen reference text, never an audio transcript. Reject uncertain transcription. '
        'Separately set speech_related=true only when the supplied short speech is semantically '
        'related to the visible reference topic. Never approve unrelated song lyrics as its hook.',
        {'purpose':'reference_screen_text_verification','proposal_sha256':proposal_sha,
         'quotes':ordered,'audio_transcription':speech},media=media)
    if (review.get('accepted') is not True or sorted(review.get('frame_ids',[])) != sorted(ids)
            or review.get('proposal_sha256') != proposal_sha):
        raise ValueError('원본 화면 문구 검토를 완료하지 못했습니다: '+str(review.get('reason',''))[:250])
    # Keep the chronological full visible phrases, including changing captions.
    phrases=list(dict.fromkeys(r['text'] for r in ordered if r['text']))
    if not phrases:
        if speech:return {'text':speech,'kind':'speech','speech_text':speech}
        raise ValueError('확인 가능한 원본 화면 문구가 없습니다.')
    keep_speech=bool(speech and first.get('use_speech_in_benchmark') is True and review.get('speech_related') is True)
    text='\n'.join(([speech] if keep_speech else [])+phrases)
    result={'text':text,'kind':'mixed' if keep_speech else 'screen_text','speech_text':speech,
            'video_sha256':identity,'evidence':evidence,'quotes':ordered,'review':review}
    _atomic_json(saved,result)
    return result
