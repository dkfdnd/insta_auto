"""Studio layout and navigation against isolated fixtures, never the live queue."""
import copy
import json
import pytest

from test_studio_board_browser import studio_page


def test_server_outage_explains_missing_list_and_recovers_without_losing_cards(studio_page):
    from playwright.sync_api import expect
    page, _ = studio_page
    def unavailable(route):
        route.abort('failed')
    page.route('**/api/studio', unavailable)
    page.reload()
    expect(page.locator('#connection')).to_be_visible()
    expect(page.locator('#board-loading')).to_be_hidden()
    page.unroute('**/api/studio', unavailable)
    page.evaluate('refreshStudio()')
    expect(page.locator('.work-card')).to_have_count(6)
    expect(page.locator('#connection')).to_be_hidden()
    page.route('**/api/studio', unavailable)
    page.evaluate('refreshStudio()')
    expect(page.locator('#connection')).to_be_visible()
    expect(page.locator('.work-card')).to_have_count(6)


def test_default_board_and_compact_three_summary_boxes(studio_page):
    from playwright.sync_api import expect
    page, _ = studio_page
    intake = dict(available=True, ready=True, selection_ready=True, enabled=True,
                  updated_at=1791300000, new_posts=32, new_hot_videos=4, created=2,
                  existing=2, rows=[], candidates=[], blocked=0)
    page.route('**/api/studio/intake', lambda route: route.fulfill(
        content_type='application/json', body=json.dumps(intake)))
    page.evaluate("localStorage.removeItem('studio-list-view')")
    page.reload()
    expect(page.locator('#filters [data-filter=all]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#work-list')).to_have_attribute('data-view', 'board')
    expect(page.locator('.kanban-column')).to_have_count(3)
    expect(page.locator('.work-card')).to_have_count(6)
    expect(page.locator('#collection-intake h2')).to_have_text('최근 수집')
    boxes = [page.locator(selector).bounding_box() for selector in
             ['.page-head', '#overview', '#collection-intake']]
    assert max(box['y'] for box in boxes) - min(box['y'] for box in boxes) < 2
    assert max(box['height'] for box in boxes) < 260
    assert page.locator('[data-intake-detail]').get_attribute('open') is None
    page.locator('[data-intake-detail] > summary').click()
    expect(page.locator('.intake-policy')).to_be_visible()
    page.locator('[data-metric=finished]').click()
    expect(page.locator('.work-card')).to_have_count(1)


def test_view_switch_preserves_status_filter_and_restores_original_progress_cards(studio_page):
    from playwright.sync_api import expect
    page, _ = studio_page
    page.locator('#filters [data-filter=running]').click()
    expect(page.locator('.work-card')).to_have_count(2)
    page.locator('[data-list-view=board]').click()
    expect(page.locator('.kanban-column')).to_have_count(3)
    expect(page.locator('#filters [data-filter=running]')).to_have_attribute('aria-pressed', 'true')
    card = page.locator('[data-work-card=voice]')
    card.locator('.card-progress-details summary').click()
    expect(card.locator('.milestone-progress')).to_be_visible()
    assert card.locator('.milestone-progress').get_attribute('aria-valuenow') == '3'
    page.evaluate('refreshStudio()')
    expect(card.locator('.milestone-progress')).to_be_visible()
    page.locator('[data-list-view=grid]').click()
    expect(page.locator('.kanban-column')).to_have_count(0)
    expect(page.locator('.work-card')).to_have_count(2)
    expect(page.locator('#filters [data-filter=running]')).to_have_attribute('aria-pressed', 'true')
    page.locator('[data-list-view=board]').click()
    expect(card.locator('.milestone-progress')).to_be_visible()


def test_board_columns_have_independent_bounded_pages(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    seed = copy.deepcopy(tasks[5])
    for i in range(10):
        item = copy.deepcopy(seed)
        item.update(id=f'done-{i:02}', created=i + 2)
        tasks.append(item)
    page.evaluate('refreshStudio()')
    page.locator('[data-list-view=board]').click()
    finished = page.locator('[data-stage=finished]')
    working = page.locator('[data-stage=working]')
    expect(finished.locator('.work-card')).to_have_count(4)
    expect(working.locator('.work-card')).to_have_count(2)
    before = working.locator('.work-card').first.get_attribute('data-work-card')
    finished.locator('[data-lane-page="2"]').click()
    expect(finished.locator('.work-card')).to_have_count(4)
    assert working.locator('.work-card').first.get_attribute('data-work-card') == before
    assert finished.locator('.column-cards').bounding_box()['height'] <= page.viewport_size['height'] * .65 + 5
    finished.locator('[data-work]').first.click()
    page.locator('#close-work').click()
    assert '5–8' in finished.locator('.lane-pagination').inner_text()


@pytest.mark.parametrize('width', [390, 1074, 1600])
def test_board_cards_stay_one_per_row_at_every_breakpoint(studio_page, width):
    from playwright.sync_api import expect
    page, _ = studio_page
    page.set_viewport_size({'width':width, 'height':900})
    page.locator('[data-list-view=board]').click()
    expect(page.locator('.kanban-column')).to_have_count(3)
    card = page.locator('[data-work-card=voice]')
    assert card.bounding_box()['width'] >= 200
    assert card.locator('h3').bounding_box()['width'] >= 80
    assert card.locator('..').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length') == 1
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_pagination_search_and_detail_return_keep_context(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    seed = copy.deepcopy(tasks[2])
    tasks[:] = []
    for index in range(29):
        item = copy.deepcopy(seed)
        item.update(id=f'work-{index:02}', title=f'테스트 영상 {index:02}', created=index + 1)
        tasks.append(item)
    page.evaluate('refreshStudio()')
    expect(page.locator('.work-card')).to_have_count(12)
    assert page.locator('.work-card').first.get_attribute('data-work-card') == 'work-28'
    page.locator('#board-pagination [data-board-page="2"]').click()
    expect(page.locator('#work-list')).to_have_attribute('data-page', '2')
    card = page.locator('.work-card').first
    card.evaluate('(e)=>window.retainedCard=e')
    before = page.evaluate('scrollY')
    card.locator('button').click()
    page.locator('#close-work').click()
    expect(page.locator('#work-list')).to_have_attribute('data-page', '2')
    assert abs(page.evaluate('scrollY') - before) < 2
    page.evaluate('refreshStudio()')
    assert page.evaluate('retainedCard===document.querySelector(".work-card")')
    page.locator('#search').fill('영상 28')
    expect(page.locator('.work-card')).to_have_count(1)
    expect(page.locator('#work-list')).to_have_attribute('data-page', '1')
    page.locator('#search').fill('')
    page.locator('#filters [data-filter=running]').click()
    tasks[-1].update(status='completed', revision=2, jobs=[])
    page.evaluate('refreshStudio()')
    expect(page.locator('#board-recent')).to_be_visible()
    expect(page.locator('#board-recent')).to_contain_text('테스트 영상 28')


def test_thumbnail_grid_mobile_and_dark_theme(studio_page):
    page, _ = studio_page
    page.set_viewport_size({'width':390, 'height':844})
    assert page.locator('#work-list').evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length') == 2
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#theme-toggle').click()
    assert page.locator('.card-cover').first.is_visible()
    page.locator('.card-cover').first.click()
    assert page.locator('#work-drawer').bounding_box()['width'] <= 390
    page.locator('#close-work').click()
    assert page.locator('.card-cover').first.is_visible()


@pytest.mark.parametrize('width', [390, 1074, 1600])
@pytest.mark.parametrize('dark', [False, True])
def test_seventy_one_selected_source_cards_never_shrink_badges_to_one_character(studio_page, width, dark):
    from playwright.sync_api import expect
    page, tasks = studio_page
    source = tasks[0]
    source['sources'] = [dict(id=f'clip-{i}', url=f'/clip-{i}.mp4',
                              source_role='context_only', blur_required=True) for i in range(71)]
    source['pipeline'][0]['artifacts']['sources'] = [dict(id=v['id']) for v in source['sources']]
    source['revision'] += 1
    page.set_viewport_size({'width':width, 'height':900})
    page.evaluate('refreshStudio()')
    if dark:
        page.evaluate("document.documentElement.dataset.theme='dark'")
    page.locator('[data-work=source]').click()
    cards = page.locator('.pf-source-used .pf-source-card')
    expect(cards).to_have_count(71)
    card = cards.first
    expect(card.locator('label')).to_be_visible()
    assert card.bounding_box()['height'] < 500
    assert card.locator('.pf-source-badges span').last.bounding_box()['width'] >= 100
    video, label, badges = [card.locator(selector).bounding_box() for selector in
                            ['video', 'label', '.pf-source-badges']]
    box = card.bounding_box()
    assert label['x'] > box['x'] + box['width'] / 2
    assert label['x'] + label['width'] <= box['x'] + box['width']
    assert label['y'] + label['height'] <= video['y'] + video['height']
    assert video['y'] + video['height'] <= badges['y']
    assert page.locator('#drawer-scroll').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    expect(page.locator('.sd-main-label [data-field=script]')).to_be_visible()
    page.locator('#detail-tabs [data-detail-tab=sources]').click()
    expect(cards.first.locator('label')).to_be_visible()


def test_source_previews_load_visible_cards_and_reveal_more_without_autoplay(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    source = tasks[0]
    source['sources'] = [dict(id=f'preview-{i}', url=f'/preview-{i}.mp4') for i in range(20)]
    source['pipeline'][0]['artifacts']['sources'] = [dict(id=v['id']) for v in source['sources']]
    source['sources'][1]['thumbnail_url'] = '/poster.jpg'
    source['revision'] += 1
    page.evaluate('refreshStudio()')
    page.locator('[data-work=source]').click()
    videos = page.locator('.pf-source-used video')
    videos.first.scroll_into_view_if_needed()
    expect(videos.first).to_have_attribute('preload', 'metadata')
    videos.first.evaluate('(v)=>window.retainedSourcePreview=v')
    page.locator('[data-field="source:preview-0"]').focus()
    page.evaluate('refreshStudio()')
    assert page.evaluate('retainedSourcePreview===document.querySelector(".pf-source-used video")')
    expect(videos.nth(1)).to_have_attribute('preload', 'none')
    expect(videos.last).to_have_attribute('preload', 'none')
    videos.last.scroll_into_view_if_needed()
    expect(videos.last).to_have_attribute('preload', 'metadata')
    assert videos.evaluate_all('(vs)=>vs.every(v=>v.paused)')
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    page.locator('#detail-tabs [data-detail-tab=sources]').click()
    expect(videos.last).to_have_attribute('preload', 'metadata')
