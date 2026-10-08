import json
from types import SimpleNamespace

from PIL import Image, ImageDraw

from hotpost.browser_search import BrowserSearcher
from hotpost.config import Settings
from hotpost.source_queries import product_query_plan
from hotpost.source_search.discovery import discover
from hotpost.source_search.planner import grounded_actions, choose_strategy, round_queries
from hotpost.source_search.strategy import (fresh_queries, image_signature, image_sha256,
                                           merge_history, fresh_frames, restore_history)


def garlic_plan():
    caption = '다진마늘에 더해 냉장보관하고 요리할 때 한 스푼씩 떠서 사용'
    plan = product_query_plan(caption, [], [], {}, [])
    plan['query_details'] = [*grounded_actions(plan, {'caption':caption}), *plan['query_details']]
    return plan


def previous(tmp_path, phase='core_action', reasons=None, audit=None):
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps({'search_strategy':{'phase':phase},
        'search_audit':audit or [], 'platform_outcomes':{'youtube':{'reasons':reasons or {}}}}), encoding='utf-8')
    return {'completed_rounds':1, 'rounds':[{'manifest_path':str(path)}]}


def test_observed_garlic_actions_precede_generic_cooking_and_keep_all_languages():
    plan = garlic_plan()
    strategy = choose_strategy(plan)
    rows = round_queries(plan, strategy)
    assert {'en','ko','zh'} == {q['language'] for q in rows}
    assert rows[0]['query'] == 'minced garlic refrigerator storage'
    assert '다진 마늘 한 스푼 떠서 사용하기' in [q['query'] for q in rows]
    assert not any('cooking tutorial' in q['query'] or 'recipe' in q['query'] for q in rows)
    assert not strategy['vendor_search']
    bare = product_query_plan('다진마늘 보관', [], [], {}, [])
    actions = grounded_actions(bare, {'caption':'다진마늘 보관'})
    assert actions and not any('refrigerator' in q['query'] or '냉장' in q['query'] for q in actions)


def test_synonyms_are_one_attempt_but_different_action_condition_or_corpus_survives():
    history = [{'provider':'youtube','query':'minced garlic preparation preparation process','status':'no_results'}]
    assert fresh_queries(['minced garlic preparation hands on preparation',
                          'minced garlic preparation detailed cooking tutorial'], 'youtube', history) == []
    assert fresh_queries(['minced garlic refrigerator storage', 'minced garlic portioning'], 'youtube', history)
    q = 'minced garlic refrigerator storage'
    history = [{'provider':'bing','query':q,'status':'no_results'}]
    assert fresh_queries([q+' raw footage no captions', q+' site:tiktok.com/@ inurl:video'], 'bing', history)
    assert fresh_queries([q], 'youtube', history) == [q]
    # Same action must not erase an explicitly different ingredient/subject.
    assert fresh_queries(['chopped onion preparation process'], 'youtube',
                         [{'provider':'youtube','query':'minced garlic preparation process','status':'results'}])
    assert fresh_queries(['蒜末准备 舀取演示'], 'bilibili',
                         [{'provider':'bilibili','query':'蒜末 用勺子舀取','status':'no_results'}]) == []


def test_quality_failure_changes_objective_and_zero_result_routes_are_skipped(tmp_path):
    plan = garlic_plan()
    context = previous(tmp_path, reasons={'quality_rejected':5}, audit=[
        {'provider':'duckduckgo','query':'garlic','status':'no_results'},
        {'provider':'yandex-images','query':'frame.jpg','language':'image','status':'no_results'}])
    strategy = choose_strategy(plan, context)
    assert strategy['phase'] == 'clean_action'
    assert 'duckduckgo' not in strategy['routes'] and 'yandex-images' not in strategy['routes']
    assert 'youtube' in strategy['routes'] and strategy['previous_failure_counts']['quality_rejected'] == 5
    assert all(q.get('search_condition') == 'clean_action' for q in round_queries(plan,strategy))
    context['completed_rounds'] = 0
    resumed = choose_strategy(plan,context)
    assert resumed['phase'] == 'clean_action' and 'duckduckgo' not in resumed['routes']
    # The following round changes again after the clean condition already ran.
    context = previous(tmp_path, reasons={'quality_rejected':3}, audit=[
        {'provider':'youtube','query':'garlic raw footage','strategy':'clean_action','status':'results','candidates':2}])
    assert choose_strategy(plan,context)['phase'] == 'scene_discovery'


def test_download_failure_uses_other_platforms_and_no_result_prefers_new_scenes(tmp_path):
    plan = garlic_plan()
    context = previous(tmp_path, reasons={'download_failed':4})
    path = tmp_path/'manifest.json'
    data = json.loads(path.read_text())
    data['platform_outcomes'] = {'bilibili':{'usable':0,'reasons':{'download_failed':4}}}
    path.write_text(json.dumps(data))
    strategy = choose_strategy(plan,context)
    assert strategy['phase'] == 'alternate_access' and strategy['routes'][0] == 'youtube'
    assert 'bilibili' not in strategy['routes']
    context = previous(tmp_path, reasons={'no_candidates':4})
    strategy = choose_strategy(plan,context)
    assert strategy['phase'] == 'scene_discovery' and strategy['routes'][0] == 'google-lens'


def test_resume_does_not_choose_exhausted_core_queries_just_because_auth_blocked_tiktok_has_unused_ones():
    plan = garlic_plan()
    queries = [q['query'] for q in round_queries(plan,choose_strategy(plan))]
    history = [{'provider':p,'query':q,'status':'no_results'}
               for p in ['youtube','bing','duckduckgo','bilibili']
               for q in [*queries,*[q+' site:tiktok.com/@ inurl:video' for q in queries]]]
    strategy = choose_strategy(plan,{'blocked_routes':['tiktok','douyin','xiaohongshu']},history)
    assert strategy['phase'] == 'clean_action'
    assert fresh_queries([q['query'] for q in round_queries(plan,strategy)],'youtube',history)


def test_recompressed_near_identical_frames_are_skipped_but_different_scene_survives(tmp_path):
    original = tmp_path/'first.jpg'
    im = Image.new('RGB',(200,300),'white')
    ImageDraw.Draw(im).rectangle((30,50,120,230),fill='brown')
    im.save(original, quality=95)
    duplicate = tmp_path/'next.jpg'; im.save(duplicate,quality=50)
    changed = tmp_path/'different.jpg'; Image.new('RGB',(200,300),'blue').save(changed)
    history = [{'provider':'yandex-images','query':original.name,'language':'image',
                'image_sha256':image_sha256(original),'image_signature':image_signature(original),'status':'no_results'}]
    assert fresh_frames([duplicate,changed],'yandex-images',history) == [changed]
    assert fresh_frames([duplicate],'google-lens',history) == [duplicate]
    assert merge_history(history)[0]['image_signature']


def test_existing_version_one_history_gets_perceptual_signatures_once(tmp_path):
    frames = tmp_path/'reference_frames'; frames.mkdir()
    p = frames/'one.jpg'; Image.new('RGB',(50,80),'green').save(p)
    manifest = tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'search_audit':[{'provider':'yandex-images','query':'one.jpg',
                                                   'language':'image','status':'no_results'}]}))
    record = {'strategy_version':1,'queries':[], 'rounds':[{'manifest_path':str(manifest)}]}
    assert restore_history(record)[0]['image_signature']
    assert record['strategy_version'] == 2
    manifest.unlink()
    assert restore_history(record)[0]['image_signature']


def test_adaptive_discovery_does_not_call_failed_routes_or_food_vendor_search(tmp_path):
    calls = []
    def search(provider):
        def invoke(qs, n, audit, *args):
            calls.extend((provider,q) for q in qs)
            audit.extend({'provider':provider,'query':q,'status':'no_results'} for q in qs)
            return []
        return invoke
    services = SimpleNamespace(search_local_hints=lambda *_:[], search_local_cache=lambda *_:[],
        search_web=search('duckduckgo'), search_bing=search('bing'), Candidate=lambda **x:x,
        search_youtube=lambda qs,n,c,a,r:search('youtube')(qs,n,a), search_pexels=lambda *_:[])
    plan = garlic_plan()
    context = previous(tmp_path,reasons={'quality_rejected':2},audit=[
        {'provider':'duckduckgo','query':'garlic','status':'no_results'}])
    strategy = choose_strategy(plan,context)
    plan['search_strategy'] = strategy
    _, _, _, audit, _ = discover(Settings(data_dir=tmp_path/'data',source_browser_search=False),'post',[],
        [q['query'] for q in round_queries(plan,strategy)], plan,[],tmp_path,[],[],lambda *_:None,services)
    assert calls and not any(provider=='duckduckgo' or 'lazada' in query for provider,query in calls)
    assert any(r['status']=='strategy_skipped' and r['provider']=='duckduckgo' for r in audit)


def test_actual_browser_request_is_checkpointed_before_navigation(tmp_path):
    searcher = BrowserSearcher(Settings(data_dir=tmp_path),tmp_path)
    seen = []
    searcher.progress = lambda message:seen.append(json.loads(json.dumps(searcher.searches)))
    row = {'provider':'bilibili','query':'蒜末','status':'started'}
    searcher.searches.append(row)
    searcher._audit_request(row,'search_navigation')
    assert seen[-1][0]['requests'][0]['operation'] == 'search_navigation'
