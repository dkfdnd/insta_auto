import json
from types import SimpleNamespace

import pytest

from hotpost.config import Settings
from hotpost.source_finder import Candidate
from hotpost.source_queries import platform_queries, language
from hotpost.source_targets import candidate_batch, select_sources, tiktok_coverage


@pytest.mark.parametrize('provider', ['douyin','xiaohongshu','bilibili'])
def test_chinese_platform_never_falls_back_to_korean_when_chinese_exhausted(provider):
    queries=['display cabinet','진열장','展示柜']
    assert platform_queries(queries,provider,6)==['展示柜']
    assert platform_queries(queries[:2],provider,6)==[]


def test_tiktok_frontloads_all_three_languages():
    queries=['display cabinet '+str(i) for i in range(8)]+['진열장','展示柜']
    assert [language(q) for q in platform_queries(queries,'tiktok',3)]==['en','ko','zh']


def source(platform, index, quality='clean-source', rejected=False):
    return Candidate(url=f'https://{platform}.com/video/{index}',provider=platform,
        downloaded_file=f'{platform}{index}.mp4',file_sha256=f'{platform}{index}',
        source_quality=quality,rejection_reasons=['low_product_or_scene_similarity'] if rejected else [])


def test_target_reserves_five_verified_unique_sources_without_promoting_bad_sources():
    pool=[source('youtube',i) for i in range(25)]
    good=[source('tiktok',i) for i in range(5)]
    bad=[source('tiktok',10,'edited-with-text',True),source('tiktok',11,rejected=True),source('tiktok',12,'unknown')]
    duplicate=source('tiktok',99);duplicate.file_sha256=good[0].file_sha256
    pool+=bad+[duplicate]+good
    batch=candidate_batch(pool,40,5)
    assert batch[0].platform=='tiktok'
    selected=select_sources(pool,20,5)
    assert len(selected)==20
    assert sum(c.platform=='tiktok' and c.source_quality=='clean-source' for c in selected)==5
    assert not bad[0].selected_for_zip and not bad[1].selected_for_zip
    assert len({c.file_sha256 for c in selected})==20
    searches=[dict(provider='tiktok',language=l,status='results') for l in ['en','ko','zh']]
    assert tiktok_coverage(pool,searches,5)['status']=='met'
    # Language coverage is diagnostic; five actual unique usable files meet
    # the quantity requirement even if one search language found them all.
    assert tiktok_coverage(pool,searches[:1],5)['status']=='met'
    assert not tiktok_coverage(pool,searches[:1],5)['search_complete']


def test_captcha_or_low_yield_is_shortfall_not_success():
    pool=[source('tiktok',0)]
    select_sources(pool,20,5)
    result=tiktok_coverage(pool,[dict(provider='tiktok',language='en',status='captcha')],5)
    assert result['usable']==1 and result['status']=='shortfall'
    assert not any(result['languages'].values())
    assert any('captcha' in r for r in result['reasons'])


def test_browser_attempts_three_languages_even_with_small_candidate_cap(tmp_path,monkeypatch):
    from hotpost import browser_search as bs
    monkeypatch.setattr(bs,'BROWSER_COOLDOWNS',{})
    page=SimpleNamespace(route=lambda *_:None,goto=lambda *a,**k:SimpleNamespace(status=200),
        wait_for_timeout=lambda _:None,mouse=SimpleNamespace(wheel=lambda *a:None),close=lambda:None)
    searcher=bs.BrowserSearcher(Settings(data_dir=tmp_path,source_queries_per_platform=1),tmp_path)
    monkeypatch.setattr(searcher,'_pace',lambda *a, **kw:None)
    monkeypatch.setattr(searcher,'_check_block',lambda *a:False)
    monkeypatch.setattr(bs,'_embedded_candidates',lambda *a:[])
    monkeypatch.setattr(bs,'_anchors',lambda p,provider,q,kind:[{'url':f'https://www.tiktok.com/@a/video/{q}'}])
    monkeypatch.setattr(searcher,'_wait_platform_results',
                        lambda p,provider,q,audit,hits:bs._anchors(p,provider,q,'platform-search'))
    searcher._platforms(SimpleNamespace(new_page=lambda:page),['cabinet','진열장','展示柜'],1,providers={'tiktok'})
    assert [r['language'] for r in searcher.searches]==['en','ko','zh']
    assert len(searcher.candidates)==1


def test_query_planning_uses_local_fallback_without_gemini(monkeypatch):
    from hotpost.source_planning import enrich_plan
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    calls=[]
    def generate(*args):
        calls.append(args)
        return {'queries':[dict(query=q,language=l,source='speech',quote='진열장')
                           for q,l in [('display cabinet','en'),('진열장','ko'),('展示柜','zh')]]}
    monkeypatch.setattr('hotpost.script_rewriter._generate',generate)
    result=enrich_plan(Settings(),{'query_details':[]},'',{'speech':'진열장'})
    assert len(calls)==1 and {r['language'] for r in result['query_details']}=={'en','ko','zh'}


def test_tiktok_shortfall_is_exposed_to_studio(tmp_path):
    from hotpost.source_audit import summarize
    from hotpost.studio import Studio
    coverage=tiktok_coverage([],[],5)
    path=tmp_path/'manifest.json'
    path.write_text(json.dumps({'candidates':[],'platform_targets':{'tiktok':coverage}}),'utf-8')
    assert summarize(path)['platform_targets']['tiktok']['status']=='shortfall'
    studio=Studio(Settings(data_dir=tmp_path),workers=False)
    state,_=studio.store.create('ref','test')
    studio._accept(state,{'kind':'refresh_sources','payload':{}},
                   {'sources':[],'source_search_manifest_path':str(path),'platform_targets':{'tiktok':coverage}})
    assert 'TikTok 0/5' in state['source_search']['message']
    assert '목표 미달' in state['source_search']['message']
