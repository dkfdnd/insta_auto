"""Source stops must be visible in the current workspace, not only in hidden history."""
from test_studio_board_browser import studio_page


def test_stopped_source_reason_visible_without_opening_search_history(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    task = tasks[0]
    task.update(status='source_wait', jobs=[], source_acquisition={'hold':{'reason':'no_progress'}},
                source_search={'status':'blocked','message':'소스 자동 수집 중지 · 인증 필요: tiktok'},
                source_goal={'count':0, 'target':10, 'ready':False, 'core_ready':False, 'platforms':{}})
    task['automation']['stage'] = 'sources'
    task['revision'] += 1
    page.evaluate('refreshStudio()')
    page.locator('[data-work="source"]').click()
    notice = page.locator('[data-source-alert]')
    expect(notice).to_be_visible()
    expect(notice).to_contain_text('소스 자동 수집 중지')
    expect(notice).to_contain_text('인증 필요: tiktok')
    expect(page.get_by_role('button', name='필요한 영상 검색하기 · 검색 기록')).to_be_visible()
    page.locator('#close-work').click()
    page.get_by_role('button', name='확인 필요', exact=True).click()
    expect(page.locator('[data-work="source"]')).to_be_visible()


def test_active_search_objective_is_visible_without_opening_advanced_history(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    task = tasks[0]
    task.update(status='source_wait', jobs=[{'id':'job-strategy','kind':'collect_sources','status':'running'}],
                source_search={'status':'running','message':'후보 검사 중','progress':60,
                               'strategy_message':'검색 전략 · 원본·무자막 행동 장면 검색 · 이전 검증 탈락'},
                source_goal={'count':4,'target':10,'ready':False,'core_ready':True,'platforms':{}})
    task['automation']['stage'] = 'sources'
    task['revision'] += 1
    page.evaluate('refreshStudio()')
    page.locator('[data-work="source"]').click()
    expect(page.locator('[data-source-alert] [data-search-strategy]')).to_be_visible()
    expect(page.locator('[data-source-alert]')).to_contain_text('이전 검증 탈락')


def test_inspection_evidence_and_parser_failure_visible_in_search_history(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    task = tasks[0]
    task.update(status='source_wait', jobs=[], source_audit={
        'selected':0, 'usable':0, 'inspection':[{'title':'Garlic fridge scoop',
            'reasons':['제목의 핵심 행동 일치: cold_storage, scoop'],
            'duration':24, 'download_budget_seconds':37.5}],
        'searches':[{'provider':'tiktok','query':'','status':'readiness_blocked'}]})
    task['revision'] += 1
    page.evaluate('refreshStudio()')
    page.locator('[data-work="source"]').click()
    page.get_by_role('button', name='필요한 영상 검색하기 · 검색 기록').click()
    options = page.locator('[data-search-options]')
    if not options.evaluate('(el)=>el.open'):
        options.locator(':scope > summary').click()
    options.get_by_text('소스 검색 내역', exact=True).click()
    options.get_by_text('후보 검사 순서의 근거와 시간 배분', exact=True).click()
    expect(options.get_by_text('Garlic fridge scoop', exact=True)).to_be_visible()
    expect(options).to_contain_text('다운로드 시간 배분 37.5초')
    expect(options).to_contain_text('검색 결과의 길이 24초')
    options.get_by_text('검색어와 실행 기록', exact=True).click()
    expect(options.get_by_text('페이지 판독 실패로 재검색 중지', exact=False)).to_be_visible()
