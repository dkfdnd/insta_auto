import copy
import hashlib
import json

import pytest

from hotpost.config import Settings
from hotpost.source_finder import Candidate
from hotpost.source_outcomes import platform_outcomes
from hotpost.source_policy import adopt_policy, current_policy
from hotpost.source_targets import select_sources
from hotpost.studio import Studio
from hotpost.studio_sources import source_goal
from hotpost.studio_workflow import init_run


def inventory(tmp_path, tiktok=5):
    sources = []
    for i in range(10):
        path = tmp_path/f'{i}.mp4'; path.write_bytes(f'unique footage {i}'.encode())
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        sources.append({'id':str(i), 'path':str(path), 'sha256':sha, 'source_quality':'clean-source',
            'origin_url':f'https://{"tiktok.com/@author/video" if i<tiktok else "youtube.com/watch?v="}/{i}',
            'functional_review':{'reviewed':True, 'same_core_function':i==0, 'observed_actions':['unfolding'],
                                 'evidence_frames':['observed.jpg'], 'source_sha256':sha}})
    return sources


def test_new_policy_requires_tiktok_even_when_other_platforms_already_have_ten(tmp_path):
    state = {'sources':inventory(tmp_path, 0), 'source_policy':current_policy(Settings(source_tiktok_min_usable=0))}
    goal = source_goal(state)
    assert goal['count']==10 and goal['core_ready'] and not goal['ready']
    assert goal['platform_targets']['tiktok']=={'target':5,'usable':0,'status':'shortfall'}
    state['sources'] = inventory(tmp_path, 5)
    assert source_goal(state)['ready']
    state['sources'][4]['origin_url']='https://fake-tiktok.com/video/4'
    assert not source_goal(state)['ready']


@pytest.mark.parametrize('active_job,tiktok,done', [(False,5,True),(True,5,False),(False,0,False)])
def test_recovered_inventory_status_does_not_hide_active_search_or_shortfall(tmp_path,active_job,tiktok,done):
    import sqlite3
    from hotpost.studio_sources import sync_ready_source_status
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE jobs(task_id TEXT,kind TEXT,status TEXT)')
    if active_job: db.execute("INSERT INTO jobs VALUES ('task','collect_sources','running')")
    state={'id':'task','sources':inventory(tmp_path,tiktok),'source_policy':current_policy(),
           'source_search':{'status':'queued','message':'old status'}}
    sync_ready_source_status(state,db)
    assert (state['source_search']['status']=='done') is done
    assert state['source_goal']['count']==10
    if not done: assert state['source_search']['message']=='old status'


@pytest.mark.parametrize('invalid', ['duplicate', 'frame_duplicate', 'missing', 'unreviewed_mask', 'ineligible'])
def test_quota_counts_only_distinct_actual_editing_ready_files(tmp_path, invalid):
    state = {'sources':inventory(tmp_path), 'source_policy':current_policy()}
    source = state['sources'][4]
    if invalid=='duplicate': source['sha256']=state['sources'][0]['sha256']
    elif invalid=='frame_duplicate':
        source['frame_hashes']=state['sources'][0]['frame_hashes']=['f'*64, 'e'*64]
    elif invalid=='missing': source['path']=str(tmp_path/'gone.mp4')
    elif invalid=='unreviewed_mask':
        source.update(source_quality='edited-with-text', watermark_masks=[{'reviewed':False}])
    else: source['editing_eligible']=False
    goal=source_goal(state)
    assert goal['count']==9 and goal['platform_targets']['tiktok']['usable']==4 and not goal['ready']


def test_completed_legacy_policy_remains_readable_and_new_run_uses_new_policy(tmp_path):
    state={'sources':inventory(tmp_path,0), 'run_id':'old', 'runs':[{'id':'old','status':'completed'}]}
    original=copy.deepcopy(state)
    assert source_goal(state)['ready']
    assert state==original
    adopt_policy(state)
    assert source_goal(state)['ready'] and 'source_policy' not in state['runs'][0]
    state.pop('run_id')
    run=init_run(state)
    assert run['source_policy']==current_policy()
    assert not source_goal(state)['ready']
    assert state['runs'][0]==original['runs'][0]


def test_store_creation_and_explicit_refresh_freeze_policy_without_changing_old_completion(tmp_path):
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    created,_=studio.store.create('new','new',{'protocol':2,'active':True})
    assert created['runs'][0]['source_policy']==current_policy()
    def historical(s,db):
        s.pop('source_policy');s['runs'][0].pop('source_policy')
        s['runs'][0]['status']='completed';s['status']='completed'
        db.execute("UPDATE jobs SET status='done'")
    state=studio.store.change(created['id'],historical)
    before=copy.deepcopy(state['runs'])
    studio.action(state['id'],'refresh-sources',{})
    after=studio.store.get(state['id'])
    job=studio.store.claim('sources')
    assert job['payload']['source_policy']==current_policy()
    assert after['status']=='completed' and after['runs']==before


def test_outcomes_separate_saved_gates_live_blocks_and_no_candidates():
    searches=[{'provider':'tiktok','query':'','status':'verification_required'} for _ in range(15)]
    searches += [{'provider':'douyin','query':'','status':'login_required'},
                 {'provider':'douyin','query':'tent','status':'login_required','requests':[{'operation':'search_navigation'}]},
                 {'provider':'youtube','query':'tent','status':'no_results'},
                 {'provider':'xiaohongshu','query':'tent','status':'rate_limited','http_status':429}]
    result=platform_outcomes([],searches,{'tiktok':5})
    assert result['tiktok']['search_attempts']==0
    assert result['tiktok']['skipped_searches']==15
    assert result['tiktok']['skipped_reasons']=={'verification_required':15}
    assert result['tiktok']['reasons']=={'not_attempted':1}
    assert result['douyin']['search_attempts']==1 and result['douyin']['reasons']=={'auth_required':1}
    assert result['youtube']['reasons']=={'no_candidates':1}
    assert result['xiaohongshu']['reasons']=={'rate_limited':1}
    assert result['instagram']['status']=='not_attempted'


def test_download_and_quality_failures_have_separate_durable_reason_codes():
    candidates=[]
    for i,error in enumerate(['CAPTCHA requested','login required','HTTP 429','connection reset']):
        candidates.append(Candidate(f'https://tiktok.com/@a/video/{i}','tiktok',
            error=error,download_attempted=True,rejection_reasons=['download_failed']))
    candidates += [Candidate('https://tiktok.com/@a/video/4','tiktok',downloaded_file='4.mp4',
                             source_quality='edited-with-text',download_attempted=True),
                   Candidate('https://tiktok.com/@a/video/5','tiktok',downloaded_file='5.mp4',
                             source_quality='clean-source',download_attempted=True,rejection_reasons=['duplicate_of:other']),
                   Candidate('https://tiktok.com/@a/video/6','tiktok',download_attempted=False,rejection_reasons=['not_probed'])]
    result=platform_outcomes(candidates,[],{'tiktok':5})['tiktok']
    assert result['download_attempts']==6 and result['usable']==0
    assert result['reasons']==dict(captcha=1,auth_required=1,rate_limited=1,download_failed=1,
                                   quality_rejected=1,duplicate=1,not_attempted=1)


def test_selected_download_waiting_for_studio_review_is_not_a_quality_failure():
    candidate = Candidate('https://tiktok.com/@a/video/4', 'tiktok', downloaded_file='4.mp4',
                          selected_for_zip=True, source_quality='edited-with-text',
                          download_attempted=False, acquisition='local-cache')
    current = platform_outcomes([candidate], [], {'tiktok': 5})['tiktok']
    assert current['usable'] == 0 and current['reasons']['review_pending'] == 1
    assert 'quality_rejected' not in current['reasons']
    assert current['network_received'] == current['download_attempts'] == 0


@pytest.mark.parametrize('platform', ['tiktok','douyin','xiaohongshu','instagram','youtube'])
def test_indexed_attempt_keeps_search_engine_channel_without_faking_site_navigation(platform):
    result=platform_outcomes([], [{'provider':'bing','query':f'tent site:{platform}.com/','status':'no_results'}])
    assert result[platform]['search_attempts']==1 and result[platform]['search_channels']==['bing']
    assert result[platform]['search_evidence'][0]['stage']=='search'


def test_http_forbidden_does_not_invent_login_failure():
    result=platform_outcomes([], [{'provider':'tiktok','query':'tent','status':'http_error','http_status':403}])
    assert result['tiktok']['reasons']=={'access_denied':1}


def test_failed_reference_preparation_writes_manifest_without_invented_platform_attempt(tmp_path,monkeypatch):
    from hotpost import source_finder as sf
    settings=Settings(data_dir=tmp_path,source_tiktok_min_usable=0)
    monkeypatch.setattr(sf,'_post',lambda *_: (_ for _ in ()).throw(RuntimeError('CAPTCHA at reference')))
    with pytest.raises(RuntimeError): sf.find_sources(settings,'ref')
    manifest=json.loads(next(settings.source_dir.glob('ref-*/manifest.json')).read_text(encoding='utf-8'))
    assert manifest['status']=='failed' and manifest['failure']['reason']=='captcha'
    assert manifest['source_policy']['platform_minimums']=={'tiktok':5}
    assert manifest['platform_outcomes']['tiktok']['reasons']=={'not_attempted':1}
    assert manifest['platform_outcomes']['tiktok']['search_attempts']==0


def test_discovery_failure_before_checkpoint_is_unknown_not_unattempted(tmp_path,monkeypatch):
    from hotpost import source_finder as sf
    from hotpost.source_audit import summarize
    settings=Settings(data_dir=tmp_path)
    def crash(_settings, _shortcode, progress, **kwargs):
        progress('provider discovery',32)
        raise RuntimeError('provider crashed before returning its audit')
    monkeypatch.setattr(sf,'_find_sources',crash)
    with pytest.raises(RuntimeError): sf.find_sources(settings,'ref')
    path=next(settings.source_dir.glob('ref-*/manifest.json'))
    manifest=json.loads(path.read_text(encoding='utf-8'))
    assert manifest['failure']['stage']=='discovery'
    assert manifest['platform_outcomes']=={}
    assert summarize(path)['execution_audit_available'] is False
