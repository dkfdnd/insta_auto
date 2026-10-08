"""Persistent source acquisition independent of script and voice production."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from .source_quality import editing_ready, sha256_file, frame_duplicate
from .source_urls import canonical_video_key
from .source_policy import run_policy, source_platform, goal_message, adopt_policy

PLATFORMS = {'tiktok':'틱톡','douyin':'더우인','xiaohongshu':'샤오홍슈',
             'instagram':'인스타그램','youtube':'유튜브','youtu.be':'유튜브','bilibili':'빌리빌리','pexels':'Pexels','lazada':'Lazada'}


def platform_name(source):
    host = urlparse(source.get('origin_url', '')).hostname or ''
    return next((name for key, name in PLATFORMS.items() if key in host), host or '기타')


def unique_sources(sources):
    result, hashes, urls = [], set(), set()
    for source in sources:
        sha = source.get('sha256')
        url = canonical_video_key(source.get('origin_url', ''))
        if (sha and sha in hashes) or (url and url in urls):
            continue
        frames = [int(v, 16) for v in source.get('frame_hashes') or []]
        if frames and any(frame_duplicate(frames, [int(v, 16) for v in prior.get('frame_hashes') or []]) for prior in result):
            continue
        hashes.add(sha); urls.add(url); result.append(source)
    return result


def source_goal(state, target=10):
    if state.get('creation_mode') == 'self_shot':
        run = next((r for r in state.get('runs', []) if r['id'] == state.get('run_id')), {})
        ids = run.get('inputs', {}).get('source_ids')
        sources = [s for s in state.get('sources', []) if s.get('rights') == 'user_supplied'
                   and Path(s.get('path') or '').is_file() and (ids is None or s['id'] in ids)]
        return {'target':1, 'maximum':20, 'count':len(sources), 'platforms':{'내 촬영':len(sources)},
                'policy_version':'self-shot-v1', 'platform_targets':{}, 'core_ready':bool(sources),
                'ready':bool(sources) and (ids is None or len(sources) == len(set(ids))),
                'source_ids':[s['id'] for s in sources]}
    policy = run_policy(state, target)
    target = policy['minimum_total']
    sources = unique_sources([s for s in state.get('sources', [])
                              if Path(s.get('path') or '').is_file() and editing_ready(s)])
    platforms = {}
    for source in sources:
        name = platform_name(source)
        platforms[name] = platforms.get(name, 0)+1
    def core(source):
        review = source.get('functional_review') or {}
        return (source.get('source_role') != 'context_only' and review.get('reviewed') is True
                and review.get('same_core_function') is True and bool(review.get('observed_actions'))
                and bool(review.get('evidence_frames')) and review.get('source_sha256') == source.get('sha256'))
    core_ready = any(core(s) for s in sources)
    platform_targets = {p: {'target': minimum, 'usable': sum(source_platform(s) == p for s in sources)}
                        for p, minimum in policy.get('platform_minimums', {}).items()}
    for coverage in platform_targets.values():
        coverage['status'] = 'met' if coverage['usable'] >= coverage['target'] else 'shortfall'
    return {'target':target, 'count':len(sources), 'platforms':platforms,
            'policy_version':policy['version'], 'platform_targets':platform_targets,
            'core_ready':core_ready, 'ready':len(sources)>=target and core_ready
                and all(c['status'] == 'met' for c in platform_targets.values()),
            'source_ids':[s['id'] for s in sources]}


def sync_ready_source_status(state, db, target=10):
    """Reconcile recovered inventory without masking a live acquisition job."""
    goal = source_goal(state, target)
    state['source_goal'] = goal
    if goal['ready'] and not db.execute(
            "SELECT 1 FROM jobs WHERE task_id=? AND kind IN ('collect_sources','refresh_sources') "
            "AND status IN ('queued','running')", (state['id'],)).fetchone():
        state['source_search'] = {'status':'done', 'message':'소스 준비 완료 · '+goal_message(goal), 'progress':100}
    return goal


class SourceAcquisitionMixin:
    def release_source_hold(self, state):
        record = state.setdefault('source_acquisition', {})
        if record.get('hold'):
            record.setdefault('hold_history', []).append(record.pop('hold'))
        record.update(bounded_rounds=0, no_progress_rounds=0, started_at=time.time(), execution_seconds=0)

    def _stop_source_collection(self, state, db, reason, details):
        record = state.setdefault('source_acquisition', {})
        hold = {'reason':reason, 'details':details, 'at':time.time(),
                'rounds':record.get('bounded_rounds', 0),
                'no_progress_rounds':record.get('no_progress_rounds', 0)}
        record['hold'] = hold
        labels = {'no_progress':'연속 수집에서 제작 가능한 소스 증가 없음',
                  'strategy_exhausted':'새로 실행할 검색 조건 없음',
                  'round_limit':'수집 회차 한도 도달', 'time_limit':'수집 총시간 한도 도달'}
        message = '소스 자동 수집 중지 · ' + labels[reason]
        if details: message += ' · ' + ' / '.join(details)
        state['source_search'] = {'status':'blocked', 'message':message, 'progress':0, 'hold':hold}
        db.execute("UPDATE jobs SET status='paused' WHERE task_id=? AND kind='collect_sources' AND status='queued'", (state['id'],))
        self.store.event(db, state['id'], 'source_collection_stopped', hold)

    def ensure_source_collection(self, state, db, *, finishing=None):
        if state.get('creation_mode') == 'self_shot':
            return
        auto = state.get('automation', {})
        if auto.get('protocol') != 2 or auto.get('paused_by_user') or auto.get('consumed_by_daily_policy'):
            return
        if not auto.get('active') or state.get('status') == 'completed' or not state.get('original_text'):
            return
        goal = source_goal(state, self.settings.source_min_usable)
        state['source_goal'] = goal
        if goal['ready']:
            state.setdefault('source_acquisition', {}).pop('hold', None)
            state['production_blockers'] = [x for x in state.get('production_blockers', []) if x != 'core_footage_gap']
            return
        running = db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind IN ('collect_sources','refresh_sources') AND status IN ('queued','running') AND id<>?", (state['id'], finishing or '')).fetchone()
        if running:
            return
        record = state.setdefault('source_acquisition', {'round':0, 'queries':[], 'urls':[]})
        record.setdefault('round', 0)
        if record.get('hold'):
            return
        from .source_search.strategy import restore_history
        restore_history(record)
        record.setdefault('queued_at', time.time())
        if record.get('bounded_rounds', 0) >= max(1, self.settings.source_collection_max_rounds):
            self._stop_source_collection(state, db, 'round_limit', [])
            return
        if record.get('execution_seconds', 0) >= max(1, self.settings.source_collection_time_budget):
            self._stop_source_collection(state, db, 'time_limit', [])
            return
        run = state.get('run_id', 'initial')
        failed = db.execute("SELECT 1 FROM jobs WHERE task_id=? AND kind='collect_sources' AND status='failed'", (state['id'],)).fetchone()
        if failed:
            return  # Persistent authentication/configuration errors need repair, not another identical request.
        policy = adopt_policy(state, self.settings)
        goal = source_goal(state, self.settings.source_min_usable)
        state['source_goal'] = goal
        job_id = self.store.enqueue(db, state['id'], 'collect_sources', {'round':record['round'], 'run_id':run, 'source_policy':policy}, f"collect:{run}:{record['round']}")
        # Each round has finite request/time budgets. Continue another strategy
        # fairly after other tasks, without turning waiting into a live spinner.
        not_before = record.get('next_attempt_at', 0)
        if not_before > time.time():
            db.execute('UPDATE jobs SET checkpoint=? WHERE id=?', (json.dumps({'not_before':not_before}), job_id))
        state['source_search'] = {'status':'queued', 'message':'자동 추가 수집 대기 · '+goal_message(goal), 'progress':0}

    def handle_source_error(self, job, error):
        from .studio_workflow import transient
        if transient(error) and job['checkpoint'].get('auto_retries',0) < 2:
            self.store.defer(job, str(error), 60)
        else:
            self.store.fail(job, error)

    def _collect_sources(self, state, job):
        # A large batch can wait hours in the durable queue. Only time spent
        # actually searching/downloading/reviewing consumes the source budget.
        started = time.monotonic()
        result = None
        try:
            result = self._collect_source_attempt(state, job)
            return result
        finally:
            if result is None or not result.get('stopped'):
                elapsed = max(0, time.monotonic()-started)
                def record_execution(s, db):
                    record = s.setdefault('source_acquisition', {})
                    record['execution_seconds'] = record.get('execution_seconds', 0)+elapsed
                self.store.change(state['id'], record_execution)

    def _collect_source_attempt(self, state, job):
        if state.get('creation_mode') == 'self_shot':
            raise ValueError('내 촬영 영상 작업에는 외부 영상을 수집하지 않습니다.')
        from .source_finder import find_sources, extract_frames
        from .source_functional import review_function, needs_function_review, apply_function_review
        from .source_overlay_review import POLICY as overlay_policy, needs_overlay_review, review_source_overlays
        from .source_review_withdrawals import apply_withdrawals
        def progress(message, pct):
            def update(s, db):
                old = s.get('source_search', {})
                strategy_message = str(message) if str(message).startswith('검색 전략 · ') else old.get('strategy_message', '')
                s['source_search'] = {'status':'running','message':str(message)[:300], 'progress':pct,
                                      'strategy_message':strategy_message[:400]}
            self.store.change(state['id'], update)
        from .source_search.strategy import restore_history
        # Recovered queued jobs also migrate pre-upgrade search manifests once.
        def initialize(s, db):
            record = s.setdefault('source_acquisition', {})
            restore_history(record)
            record.setdefault('started_at', time.time())
            if not record.get('hold') and record.get('bounded_rounds', 0) >= max(1, self.settings.source_collection_max_rounds):
                self._stop_source_collection(s, db, 'round_limit', [])
            if not record.get('hold') and record.get('execution_seconds', 0) >= max(1, self.settings.source_collection_time_budget):
                self._stop_source_collection(s, db, 'time_limit', [])
        state = self.store.change(state['id'], initialize)
        acquisition = state.get('source_acquisition', {})
        if acquisition.get('hold'):
            return {'stopped':True}
        result = None
        visual_review_only = False
        manifest_path = job['checkpoint'].get('manifest')
        if manifest_path and Path(manifest_path).is_file():
            result = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
        if result is None:
            pending = [s for s in state.get('sources', [])
                       if Path(s['path']).is_file() and needs_overlay_review(s)]
            if pending:
                # Finish the missing local review before requesting more files.
                # This spends execution time but no external-search round/failure.
                visual_review_only = True
                manifest_path = state.get('source_search_manifest_path') or state['manifest_path']
                result = {'candidates':[], 'source_policy':state.get('source_policy'),
                          'search_audit':[{'provider':'saved-overlay-review','status':'results',
                                           'query':'','candidates':len(pending)}]}
            else:
                result = find_sources(self.settings, state['shortcode'], progress,
                    search_round=job['payload'].get('round',0),
                    previous_searches=acquisition.get('queries', []), exclude_urls=acquisition.get('urls', []),
                    search_context={'completed_rounds':acquisition.get('bounded_rounds',0),
                                    'rounds':acquisition.get('rounds',[])})
                manifest_path = str(Path(result['zip_path']).parent/'manifest.json')
                job['checkpoint']['manifest'] = manifest_path
                self.store.checkpoint(job['id'], job['checkpoint'])
        manifest = Path(manifest_path)
        candidates = [c for c in result.get('candidates',[]) if c.get('selected_for_zip')]
        files = [manifest.parent/c['downloaded_file'] for c in candidates if c.get('downloaded_file')]
        incoming = self._source_records(files, manifest)
        # Review saved sources too; previously downloaded context footage stays
        # usable, while a high appearance score alone cannot assert core action.
        merged = unique_sources([*copy.deepcopy(state['sources']), *incoming])
        frames = extract_frames(Path(state['reference_video']), self.folder(state['id'])/'source-reference', max_frames=6)
        reviewed = []
        review_completion = None
        for index, source in enumerate(merged, 1):
            if not Path(source['path']).is_file(): continue
            if 'reviewed_intervals' in source or source.get('mask_review'):
                source = apply_withdrawals(self.settings, source)
            if (source.get('source_interval_withdrawal') and not source.get('reviewed_intervals')):
                reviewed.append(source)
                continue
            if source.get('overlay_review_error') and not needs_overlay_review(source):
                # Function similarity cannot reverse a failed overlay approval.
                source['editing_eligible'] = False
                reviewed.append(source)
                continue
            if needs_overlay_review(source):
                progress(f'사용할 장면의 글자·블러 확인 {index}/{len(merged)}',90)
                try:
                    source = review_source_overlays(self.settings, source,
                        self.folder(state['id'])/'source-mask-checks'/source['sha256'][:20])
                    source.pop('overlay_review_error', None)
                except Exception as exc:
                    # A failed visual approval keeps the source for diagnosis,
                    # but cannot count toward quotas or silently become clean.
                    source['editing_eligible'] = False
                    source['overlay_review_error'] = str(exc)[:500]
                    source['overlay_review_attempted_policy'] = overlay_policy
                    source['overlay_review_attempted_sha256'] = source['sha256']
                    reviewed.append(source)
                    continue
            if source.get('source_interval_withdrawal') and not source.get('reviewed_intervals'):
                reviewed.append(source)
                continue
            review = source.get('functional_review') or {}
            if needs_function_review(source):
                progress(f'사용할 핵심·보조 장면 확인 {index}/{len(merged)}',94)
                mask_review = source.get('mask_review') or {}
                if mask_review.get('source_sha256') == source['sha256'] and source.get('reviewed_intervals'):
                    candidate_frames = [Path(f['path']) for f in mask_review.get('evidence_frames', [])
                        if any(w['source_start'] <= f['source_timestamp'] < w['source_end']
                               for w in source['reviewed_intervals'])]
                else:
                    candidate_frames = extract_frames(Path(source['path']), self.folder(state['id'])/'source-checks'/source['sha256'][:20], max_frames=6)
                review = review_function(self.settings, SimpleNamespace(file_sha256=source['sha256']), frames, candidate_frames)
            apply_function_review(source, review)
            reviewed.append(source)
            if state.get('automation', {}).get('active') and job['kind'] == 'collect_sources':
                # Only completed task-scoped reviews can finish the automatic
                # acquisition goal. Extra downloads stay in the original
                # manifest/library; they are not approved for this edit.
                goal = source_goal({**state, 'sources': reviewed}, self.settings.source_min_usable)
                if goal['ready']:
                    review_completion = {'reason': 'quota_met', 'checked_sources': index,
                        'reviewed_sources': len(reviewed), 'available_sources': len(merged),
                        'deferred_sources': len(merged)-index, 'goal': goal}
                    progress('사용 소스 검토 완료 · '+goal_message(goal), 100)
                    break
        from .source_audit import reviewed_platform_outcomes
        outcomes = (reviewed_platform_outcomes(manifest, result, reviewed)
                    if not visual_review_only and result.get('execution_audit_available', 'search_audit' in result)
                    else result.get('platform_outcomes', {}))
        return {'sources':reviewed, 'source_search_manifest_path':str(manifest),
                'source_policy':result.get('source_policy'), 'platform_outcomes':outcomes,
                'searches':result.get('search_audit', []),
                'attempted_urls':[c.get('original_url') or c.get('url') for c in result.get('candidates', []) if c.get('downloaded_file') or c.get('error')],
                'visual_review_only':visual_review_only,
                'review_completion':review_completion,
                'round':job['payload'].get('round',0)}

    def accept_source_round(self, state, job, result, db):
        if result.get('stopped'):
            return
        before = source_goal(state, self.settings.source_min_usable)
        old_by_hash = {s['sha256']:s for s in state['sources']}
        from .studio_store import uid
        for source in result['sources']:
            old = old_by_hash.get(source['sha256'])
            if old:
                # Preserve stable source IDs used by existing rendered plans.
                old.update({k:v for k,v in source.items() if k != 'id'})
            else:
                source['id'] = uid('source-'); state['sources'].append(source)
        record = state.setdefault('source_acquisition', {})
        record['round'] = max(record.get('round',0), result['round']+1)
        from .source_search.strategy import merge_history, attempted, stop_diagnostics
        record['queries'] = merge_history(record.get('queries', []), result.get('searches', []))
        record['urls'] = list(dict.fromkeys([*record.get('urls',[]), *result.get('attempted_urls',[])]))
        record.setdefault('rounds', []).append({'job_id':job['id'], 'round':result['round'],
            'manifest_path':result['source_search_manifest_path'], 'source_policy':result.get('source_policy'),
            'platform_outcomes':result.get('platform_outcomes', {}),
            'review_completion':result.get('review_completion')})
        goal = source_goal(state, self.settings.source_min_usable)
        def score(g):
            return [min(g['count'], g['target']), int(g['core_ready']), *[min(v['usable'], v['target'])
                for _, v in sorted(g.get('platform_targets', {}).items())]]
        prior = record.get('progress_high_water', score(before))
        current = score(goal)
        improved = any(c > p for c, p in zip(current, prior))
        record['progress_high_water'] = [max(c, p) for c, p in zip(current, prior)]
        if not result.get('visual_review_only'):
            record['bounded_rounds'] = record.get('bounded_rounds', 0) + 1
            record['no_progress_rounds'] = 0 if improved else record.get('no_progress_rounds', 0) + 1
        elif improved:
            record['no_progress_rounds'] = 0
        record['next_attempt_at'] = time.time()+min(600,max(30,self.settings.source_browser_search_interval))
        state.update(source_goal=goal, source_search_manifest_path=result['source_search_manifest_path'])
        state['source_search'] = {'status':'done' if goal['ready'] else 'queued',
            'message':f"{'소스 준비 완료' if goal['ready'] else '다른 방법으로 자동 추가 수집'} · "+goal_message(goal), 'progress':100 if goal['ready'] else 0}
        searches = result.get('searches', [])
        if goal['ready']:
            record.pop('hold', None)
        elif not result.get('visual_review_only') and 'searches' in result and not improved and not any(attempted(s) or
                s.get('provider') in {'operator-shortlist','deferred-candidates','local-cache','source-library'} and s.get('candidates') for s in searches):
            self._stop_source_collection(state, db, 'strategy_exhausted', stop_diagnostics(searches, goal, result.get('platform_outcomes')))
        elif not result.get('visual_review_only') and record.get('no_progress_rounds', 0) >= max(1, self.settings.source_no_progress_rounds):
            self._stop_source_collection(state, db, 'no_progress', stop_diagnostics(searches, goal, result.get('platform_outcomes')))
        self.ensure_source_collection(state, db, finishing=job['id'])
        # A collection result must not automatically repeat a failed voice/model
        # request. That failure keeps its own bounded retry policy.
        if not state.get('error') and state.get('status') != 'completed':
            self._advance_auto(state, db)
