"""Daily material acquisition ranked by views per follower, separately from spikes."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .production import file_lock
from .storage import Storage


def candidates(report, settings):
    followers = {row['username']: row.get('followers', 0) for row in report['accounts']}
    selected = []
    for post in report['posts']:
        count = followers.get(post['username'], 0)
        views = post.get('views')
        if (post.get('kind') != 'reel' or not count or views is None
                or views < settings.acquisition_min_views):
            continue
        if post.get('metric_status', {}).get('views') in ('missing', 'stale', 'legacy_unverified'):
            continue
        ratio = views / count
        if ratio >= settings.acquisition_min_views_per_follower:
            selected.append({'shortcode': post['shortcode'], 'username': post['username'],
                             'views': views, 'followers': count, 'views_per_follower': ratio})
    selected.sort(key=lambda row: (row['views_per_follower'], row['views']), reverse=True)
    return selected


def acquire(settings, report, progress=print, workers=None):
    if report.get('is_sample'):
        raise ValueError('샘플 리포트로 외부 자료를 수집하지 않습니다.')
    if workers is None:
        from .transcript import extract_transcript
        from .source_finder import find_sources
        workers = {'transcript': extract_transcript, 'source': find_sources}
    results = []
    completed_reels = 0
    with file_lock(settings.production_dir / 'execution.lock'):
        store = Storage(settings.db_path)
        try:
            for post in candidates(report, settings):
                if completed_reels >= settings.acquisition_daily_limit:
                    break
                needed = []
                for kind in ('transcript', 'source'):
                    previous = store.conn.execute(
                        "SELECT result_path FROM jobs WHERE kind=? AND shortcode=? AND status='done' ORDER BY created_at DESC",
                        (kind, post['shortcode'])).fetchall()
                    if not any(row['result_path'] and Path(row['result_path']).is_file() for row in previous):
                        needed.append(kind)
                if not needed:
                    continue
                completed_reels += 1
                for kind in needed:
                    job, created = store.create_job(uuid.uuid4().hex[:12], kind, post['shortcode'])
                    if not created:
                        continue
                    store.update_job(job['id'], status='running', started_at=int(time.time()))
                    try:
                        progress(f"{post['shortcode']} · {kind} · 팔로워 대비 {post['views_per_follower']:.2f}배")
                        result = workers[kind](settings, post['shortcode'], lambda message, pct: None)
                        path = result.get('zip_path') or result.get('json_path')
                        if not path or not Path(path).is_file():
                            raise ValueError('자료 결과 파일이 없습니다.')
                        if kind == 'source' and not result.get('downloaded', 0):
                            raise ValueError('사용 가능한 소스 영상을 확보하지 못했습니다.')
                        if kind == 'transcript' and not any(row.get('text', '').strip() for row in result.get('speech', [])):
                            raise ValueError('원본 발화 대본을 확보하지 못했습니다.')
                        store.update_job(job['id'], status='done', progress=100,
                            result_json=json.dumps(result, ensure_ascii=False), result_path=str(path or ''),
                            message='자료 확보 완료', finished_at=int(time.time()))
                        results.append({'id': job['id'], 'kind': kind, 'status': 'done'})
                    except Exception as exc:
                        store.update_job(job['id'], status='error', error=str(exc)[:600],
                                         message='자료 확보 실패', finished_at=int(time.time()))
                        results.append({'id': job['id'], 'kind': kind, 'status': 'error'})
        finally:
            store.close()
    return results
