import json
import subprocess
from types import SimpleNamespace

from hotpost.browser_search import BrowserSearcher
from hotpost.config import Settings
from hotpost.source_finder import Candidate
from hotpost.source_queries import product_query_plan
from hotpost.source_search.planner import choose_strategy, grounded_actions
from hotpost.source_search.readiness import (record_unresolved, readiness_blocked, readiness_record,
                                           parser_revision, request_readiness_recheck)
from hotpost.source_search.triage import rank_candidates, discovery_duration_reasons, deferred_candidates
from hotpost.source_search.strategy import merge_history, stop_diagnostics
from hotpost.source_targets import candidate_batch
from test_source_probe_budget import probe_run


def garlic_plan():
    caption='다진마늘 냉장 보관하고 한 스푼씩 떠서 사용'
    plan=product_query_plan(caption,[],[],{},[])
    plan['query_details']=[*grounded_actions(plan,{'caption':caption}),*plan['query_details']]
    return plan


def test_unknown_page_gate_survives_restart_and_no_new_keyword_creates_navigation(tmp_path):
    record_unresolved(tmp_path,'tiktok','garlic storage')
    record=readiness_record(tmp_path,'tiktok')
    assert record['reason']=='page_unresolved' and readiness_blocked(tmp_path,'tiktok')
    searcher=BrowserSearcher(Settings(data_dir=tmp_path),tmp_path/'debug')
    context=SimpleNamespace(new_page=lambda:(_ for _ in ()).throw(AssertionError('Unexpected navigation')))
    searcher._platforms(context,['a different garlic query'],10,providers={'tiktok'})
    assert searcher.searches[-1]['status']=='readiness_blocked'
    assert not searcher.searches[-1].get('requests')
    assert '판독 실패' in ' '.join(stop_diagnostics(searcher.searches,{'core_ready':True}))


def test_repaired_parser_or_explicit_session_check_allows_one_check_not_auth_bypass(tmp_path,monkeypatch):
    from hotpost.source_search import readiness
    from hotpost.search_access import request_manual_recheck, manual_required, access_record
    record_unresolved(tmp_path,'tiktok','garlic')
    old=parser_revision('tiktok')
    monkeypatch.setattr(readiness,'parser_revision',lambda p:old+'-fixed')
    assert not readiness_blocked(tmp_path,'tiktok')
    record_unresolved(tmp_path,'tiktok','garlic')
    assert readiness_blocked(tmp_path,'tiktok')
    assert request_manual_recheck(tmp_path,'tiktok')
    assert not readiness_blocked(tmp_path,'tiktok')
    record_unresolved(tmp_path,'tiktok','another')
    assert readiness_blocked(tmp_path,'tiktok')
    path=tmp_path/'search_cooldowns'/'tiktok.json';path.parent.mkdir()
    path.write_text(json.dumps({'reason':'captcha','requires_verification':True,'until':0}))
    assert request_readiness_recheck(tmp_path,'tiktok')
    assert manual_required(access_record(tmp_path,'tiktok'))


def test_current_parser_failure_changes_planned_route_and_survives_history_merge(tmp_path):
    row={'provider':'tiktok','query':'garlic','status':'page_unresolved','parser_revision':parser_revision('tiktok')}
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'search_audit':[row]}))
    context={'completed_rounds':1,'rounds':[{'manifest_path':str(manifest)}]}
    strategy=choose_strategy(garlic_plan(),context)
    assert 'tiktok' not in strategy['routes'] and '판독' in strategy['skipped_routes']['tiktok']
    assert merge_history([row])[0]['parser_revision']==parser_revision('tiktok')
    context['rechecked_routes']=['tiktok']
    assert 'tiktok' in choose_strategy(garlic_plan(),context)['routes']


def test_action_matching_keyword_precedes_generic_visual_clip_without_approving_it():
    generic=Candidate('https://youtube.com/watch?v=generic','youtube',title='Minced garlic cooking recipe',match_kind='visual-match')
    relevant=Candidate('https://youtube.com/watch?v=core','youtube',title='Minced garlic refrigerator storage')
    unknown=Candidate('https://youtube.com/watch?v=unknown','youtube')
    ordered=candidate_batch(rank_candidates([generic,relevant,unknown],garlic_plan()),10,5)
    assert ordered[0] is relevant and unknown in ordered
    assert relevant.discovery_reasons and not relevant.selected_for_zip and relevant.match_quality=='unverified'


def test_broader_ingredient_title_precedes_unrelated_leftovers_without_approval():
    unrelated=Candidate('https://youtube.com/watch?v=unrelated','youtube',title='ASMR triggers')
    broader=Candidate('https://youtube.com/watch?v=broader','youtube',title='How to store fresh garlic')
    specific=Candidate('https://youtube.com/watch?v=specific','youtube',title='Minced garlic refrigerator storage')
    ranked=candidate_batch(rank_candidates([unrelated,broader,specific],garlic_plan()),10,5)
    assert ranked==[specific,broader,unrelated]
    assert not broader.selected_for_zip


def test_only_known_discovery_duration_is_prechecked_not_unknown_metadata():
    c=Candidate('https://youtube.com/watch?v=short','youtube',discovery_meta={'duration':2})
    assert discovery_duration_reasons(c,1800)==['invalid_duration']
    c.discovery_meta={'duration':800}
    assert not discovery_duration_reasons(c,1800)
    c.discovery_meta={}
    assert not discovery_duration_reasons(c,1800)


def test_deferred_shortlist_excludes_failed_rejected_checked_and_canonical_duplicate_urls(tmp_path):
    p=tmp_path/'manifest.json'
    common={'provider':'youtube','title':'Garlic storage','query':'garlic'}
    rows=[{**common,'url':'https://youtube.com/watch?v=pending','download_attempted':False,'rejection_reasons':['platform_budget_exhausted']},
          {**common,'url':'https://youtu.be/pending','download_attempted':False},
          {**common,'url':'https://youtube.com/watch?v=failed','error':'timeout','download_attempted':True,'rejection_reasons':['download_failed']},
          {**common,'url':'https://youtube.com/watch?v=wrong','downloaded_file':'clip.mp4','rejection_reasons':['different_core_function']},
          {**common,'url':'https://youtube.com/watch?v=short','download_attempted':False,'rejection_reasons':['invalid_duration']},
          {**common,'url':'https://youtube.com/watch?v=checked','download_attempted':False},
          {**common,'url':'https://youtube.com/watch?v=globalstop','download_attempted':None}]
    p.write_text(json.dumps({'candidates':rows}))
    result=deferred_candidates({'rounds':[{'manifest_path':str(p)}]},['https://youtu.be/checked'],10)
    assert [c.url for c in result]==['https://youtube.com/watch?v=pending','https://youtube.com/watch?v=globalstop']
    assert all(c.match_kind=='deferred-candidate' and not c.selected_for_zip and c.download_attempted is None for c in result)


def test_first_timeout_leaves_same_platform_next_candidate_a_real_inspection_opportunity(probe_run,monkeypatch):
    from hotpost import source_finder as sf
    original=sf.download_candidate
    def download(candidate,directory,index,*args,deadline,**kwargs):
        if candidate.url.endswith('first'):
            probe_run.attempts.append({'url':candidate.url,'started':probe_run.clock.now,'deadline':deadline})
            probe_run.clock.now=deadline
            raise subprocess.TimeoutExpired('download',60)
        return original(candidate,directory,index,*args,deadline=deadline,**kwargs)
    monkeypatch.setattr(sf,'download_candidate',download)
    result=probe_run.run()
    assert len(probe_run.attempts)==2 and result['platform_probe_seconds']=={'youtube':62.0}
    second=next(c for c in result['candidates'] if c['url'].endswith('second'))
    assert second['downloaded_file'] and 'different_core_function' in second['rejection_reasons']
    assert result['downloaded']==0  # Giving it a chance never lowers eligibility.


def test_discovery_length_failure_uses_no_download_or_heavy_review_budget(probe_run,monkeypatch):
    from hotpost import source_finder as sf
    monkeypatch.setattr(sf,'search_local_hints',lambda *_:[
        Candidate('https://youtube.com/watch?v=short','youtube',discovery_meta={'duration':2}),
        Candidate('https://youtube.com/watch?v=valid','youtube')])
    result=probe_run.run()
    assert [c['url'] for c in probe_run.attempts]==['https://youtube.com/watch?v=valid']
    assert result['platform_outcomes']['youtube']['reasons']['metadata_rejected']==1


def test_uninspected_candidates_continue_without_another_search(probe_run,monkeypatch,tmp_path):
    from hotpost import source_finder as sf
    p=tmp_path/'deferred.json';p.write_text(json.dumps({'candidates':[
        {'url':'https://youtube.com/watch?v=pending','provider':'youtube',
         'download_attempted':False,'rejection_reasons':['platform_budget_exhausted']}]}))
    monkeypatch.setattr(sf,'search_local_hints',lambda *_:[])
    monkeypatch.setattr(sf,'search_web',lambda *a:(_ for _ in ()).throw(AssertionError('No repeated discovery')))
    result=sf.find_sources(probe_run.settings,'ref',search_context={'rounds':[{'manifest_path':str(p)}]})
    assert result['search_audit'][0]['provider']=='deferred-candidates'
    assert probe_run.attempts[0]['url'].endswith('pending')
