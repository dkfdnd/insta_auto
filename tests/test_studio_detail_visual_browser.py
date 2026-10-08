"""Independent detail UX audit with isolated tasks; never writes the user's queue."""
from pathlib import Path

import pytest

from test_studio_board_browser import studio_page

OUT = Path('C:/Codex/outputs/studio-detail-refresh-20261007')
LONG = '\n'.join(f'{i + 1}. 다진 마늘을 얼려 놓으면 꺼낼 때마다 불편하죠. 한 스푼씩 편하게 보관하고 필요한 만큼 꺼내 쓰세요.' for i in range(28))


def prepare(page, tasks):
    t = tasks[0]
    t['title'] = '마늘 보관통 · 상세 UX 독립 검증'
    t['sources'] = [dict(id=f'visual-{i}', url=f'/visual-{i}.mp4', thumbnail_url='/visual-poster.svg',
                         original_name=f'마늘 보관과 한 스푼 떠 쓰는 장면 {i + 1}.mp4',
                         source_role='context_only', blur_required=True) for i in range(77)]
    t['pipeline'][0]['artifacts']['sources'] = [dict(id=v['id']) for v in t['sources']]
    t['reference_url'] = '/reference.mp4'
    t['original_text'] = LONG
    t['original_evidence'] = dict(speech=[dict(start=0, text=LONG)], screen_text=[dict(text='화면 속 자막')])
    t['scripts'][0]['text'] = LONG
    t['script_candidates'] = [dict(id=f'candidate-{i}', text=LONG[:500]) for i in range(3)]
    t['selected_candidate'] = 0
    t['voices'] = [dict(id='visual-voice', path_url='/tone.wav', duration=10, script_id='s1')]
    t['voice_id'] = 'visual-voice'
    t['revision'] += 1
    poster = '<svg xmlns="http://www.w3.org/2000/svg" width="360" height="640"><rect width="360" height="640" fill="#345a43"/><circle cx="180" cy="280" r="95" fill="#e8dfc4"/><text x="180" y="430" text-anchor="middle" fill="white" font-size="26">마늘 촬영 영상</text></svg>'
    page.route('**/visual-poster.svg', lambda r: r.fulfill(content_type='image/svg+xml', body=poster))
    real_video = Path('C:/Codex/outputs/self-shot-live-20261007/final-short.mp4')
    if real_video.is_file():
        video_bytes = real_video.read_bytes()
        def reference_route(route):
            requested = route.request.headers.get('range')
            start, end = 0, len(video_bytes) - 1
            if requested:
                bounds = requested.removeprefix('bytes=').split('-')
                start = int(bounds[0] or 0)
                end = int(bounds[1]) if bounds[1] else end
            route.fulfill(status=206 if requested else 200, content_type='video/mp4',
                          headers={'Accept-Ranges':'bytes', **({'Content-Range':f'bytes {start}-{end}/{len(video_bytes)}'} if requested else {})},
                          body=video_bytes[start:end + 1])
        page.route('**/reference.mp4', reference_route)
    page.evaluate('refreshStudio()')
    page.locator('#work-list [data-work=source]').click()


def assert_no_overflow(page):
    assert page.locator('#drawer-scroll').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')


def capture(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / name))


@pytest.mark.parametrize('width', [390, 1074, 1600, 1920])
@pytest.mark.parametrize('dark', [False, True])
def test_detail_all_requested_views_render_without_overflow(studio_page, width, dark):
    from playwright.sync_api import expect
    page, tasks = studio_page
    page.set_viewport_size(dict(width=width, height=1000))
    if dark:
        page.locator('#theme-toggle').click()
    prepare(page, tasks)
    suffix = f'{width}-{"dark" if dark else "light"}'

    tabs = page.locator('#detail-tabs button')
    for tab in ['sources', 'script', 'voice', 'edit', 'results']:
        page.locator(f'#detail-tabs [data-detail-tab={tab}]').click()
        expect(page.locator('#detail-tabs [aria-pressed=true]')).to_have_count(1)
        page.wait_for_timeout(350)  # Let the existing tab background transition settle.
        active = page.locator(f'#detail-tabs [data-detail-tab={tab}]')
        assert active.get_attribute('aria-pressed') == 'true'
        active_color = active.evaluate('(e)=>getComputedStyle(e).backgroundColor')
        contrast = active.evaluate('''(e)=>{
            const rgb=v=>v.match(/[\\d.]+/g).slice(0,3).map(Number);
            const luminance=v=>rgb(v).map(x=>{x/=255;return x<=.04045?x/12.92:((x+.055)/1.055)**2.4;}).reduce((s,x,i)=>s+x*[.2126,.7152,.0722][i],0);
            const title=e.querySelector('strong'), a=luminance(getComputedStyle(e).backgroundColor),b=luminance(getComputedStyle(title).color);
            return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        }''')
        assert contrast >= 4.5
        assert tabs.evaluate_all('(buttons)=>buttons.filter(b=>b.getAttribute("aria-pressed")!=="true").every(b=>getComputedStyle(b).backgroundColor!==getComputedStyle(buttons.find(x=>x.getAttribute("aria-pressed")==="true")).backgroundColor)')
        assert active_color not in ['rgba(0, 0, 0, 0)', 'transparent']
        assert active.evaluate('''(e)=>{
            const button=e.getBoundingClientRect(),nav=e.parentElement.getBoundingClientRect();
            return button.left>=Math.max(nav.left,0)-1 && button.right<=Math.min(nav.right,innerWidth)+1;
        }'''), f'{tab} selected menu is clipped at {width}px: ' + str(active.evaluate('''e=>{
            const n=e.parentElement,b=e.getBoundingClientRect(),r=n.getBoundingClientRect();
            return {button:[b.left,b.right],nav:[r.left,r.right],scroll:n.scrollLeft,width:n.clientWidth,total:n.scrollWidth,overflow:getComputedStyle(n).overflowX};
        }'''))
        # The state beside the selected title must remain readable, not wrap
        # each Korean character into a vertical strip on narrow windows.
        status = active.locator('.glass-step-status')
        assert status.bounding_box()['height'] <= 56

    page.locator('#detail-tabs [data-detail-tab=sources]').click()
    grid = page.locator('.pf-source-used .pf-sources')
    cards = grid.locator('.pf-source-card')
    expect(cards).to_have_count(77)
    expected_columns = 2 if width <= 750 else 3 if width <= 1100 else 5
    assert grid.evaluate('(e)=>getComputedStyle(e).gridTemplateColumns.split(" ").length') == expected_columns
    b = [cards.nth(i).bounding_box() for i in range(expected_columns + 1)]
    assert max(v['y'] for v in b[:expected_columns]) - min(v['y'] for v in b[:expected_columns]) < 2
    assert b[-1]['y'] > b[0]['y'] + b[0]['height'] - 2
    first = cards.first
    check = first.locator('.sd-source-check')
    card_box, check_box = first.bounding_box(), check.bounding_box()
    assert abs(card_box['x'] + card_box['width'] - check_box['x'] - check_box['width'] - 8) <= 3
    assert abs(check_box['y'] - card_box['y'] - 8) <= 3
    assert check.inner_text().strip() == ''
    assert first.locator('input').get_attribute('aria-label') == '영상 1 사용'
    assert first.locator('.pf-source-badges').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
    first.scroll_into_view_if_needed()
    assert_no_overflow(page)
    capture(page, f'sources-{suffix}.png')

    bell = page.get_by_role('button', name='영상 준비 알림', exact=True)
    bell.click()
    popover = page.locator('.sd-notice-popover')
    expect(popover).to_be_visible()
    box = popover.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
    assert_no_overflow(page)
    capture(page, f'notice-{suffix}.png')
    page.locator('.sd-source-stage h3').click()
    expect(popover).to_be_hidden()

    page.locator('#detail-tabs [data-detail-tab=script]').click()
    script = page.locator('[data-pf-section=script] textarea[data-field=script]')
    expect(script).to_have_value(LONG)
    assert script.evaluate('(e)=>e.scrollHeight<=e.clientHeight+2 && getComputedStyle(e).overflowY==="hidden"')
    assert page.locator('.sd-script-candidates article').count() == 3
    assert page.get_by_text('이전 대본 복원하기', exact=True).count() == 0
    assert page.get_by_text('후보·이전 대본과 검사 도구', exact=True).count() == 0
    script.scroll_into_view_if_needed()
    assert_no_overflow(page)
    capture(page, f'script-{suffix}.png')
    page.get_by_role('button', name='참고할 원본 영상과 대본 보기', exact=True).click()
    reference = page.locator('.sd-reference')
    expect(reference).to_be_visible()
    expect(reference.locator('[data-reference-preview]')).to_be_visible()
    assert reference.locator('.sd-script-text').inner_text() == LONG
    assert reference.locator('textarea,button').count() == 0
    assert reference.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
    reference.locator('[data-reference-preview]').scroll_into_view_if_needed()
    assert_no_overflow(page)
    capture(page, f'reference-{suffix}.png')

    page.locator('#detail-tabs [data-detail-tab=voice]').click()
    expect(page.get_by_role('heading', name='현재 음성', exact=True)).to_be_visible()
    page.get_by_role('button', name='수정하기', exact=True).click()
    voice_script = page.locator('[data-pf-section=voice] textarea[data-field=script]')
    expect(voice_script).to_be_visible()
    assert voice_script.evaluate('(e)=>e.scrollHeight<=e.clientHeight+2 && getComputedStyle(e).overflowY==="hidden"')
    voice_script.fill(LONG + '\n' + '아래 내용을 고치면 대본에 반영됩니다. ' * 30)
    assert voice_script.evaluate('(e)=>e.scrollHeight<=e.clientHeight+2')
    page.get_by_role('button', name='목소리·속도 바꾸기', exact=True).click()
    settings = page.locator('[data-detail-panel="sd-source-voice-options"]')
    assert settings.locator('input,textarea,select').count() == 2
    assert settings.locator('[data-field=speed]').is_visible()
    assert page.get_by_text('수정 전 음성', exact=True).count() == 0
    settings.scroll_into_view_if_needed()
    assert page.locator('#detail-tabs [data-detail-tab=voice]').evaluate('''(e)=>{
        const b=e.getBoundingClientRect();return b.left>=-1 && b.right<=innerWidth+1;
    }''')
    assert_no_overflow(page)
    capture(page, f'voice-{suffix}.png')


def test_background_click_closes_work_drawer_and_focus_returns(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    prepare(page, tasks)
    backdrop = page.locator('#work-backdrop')
    expect(backdrop).to_be_visible()
    # Real pointer hit outside the drawer, rather than calling its close handler.
    page.mouse.click(20, 500)
    expect(page.locator('#work-drawer')).to_be_hidden()
    assert not page.locator('main').evaluate('(e)=>e.inert')
    assert page.locator('#work-list [data-work=source]').evaluate('(e)=>document.activeElement===e')


def test_selected_menu_remains_visible_when_window_narrows(studio_page):
    from playwright.sync_api import expect
    page, tasks = studio_page
    prepare(page, tasks)
    active = page.locator('#detail-tabs [data-detail-tab=results]')
    active.click()
    page.set_viewport_size(dict(width=390, height=1000))
    expect(active).to_have_attribute('aria-pressed', 'true')
    page.wait_for_function('''()=>{
        const b=document.querySelector('#detail-tabs [aria-pressed=true]').getBoundingClientRect();
        return b.left>=-1 && b.right<=innerWidth+1;
    }''')


@pytest.mark.parametrize('work,tab', [('voice', 'voice'), ('edit', 'edit'), ('done', 'results')])
@pytest.mark.parametrize('entry', ['card', 'link'])
def test_initial_selected_menu_visible_on_mobile_and_reopen(studio_page, work, tab, entry):
    from playwright.sync_api import expect
    page, _ = studio_page
    page.set_viewport_size(dict(width=390, height=1000))
    if entry == 'link':
        page.goto(f'http://studio.test/studio.html?work={work}')
    else:
        page.locator(f'[data-work="{work}"]').click()
    expect(page.locator('#work-drawer')).to_be_visible()
    active = page.locator(f'#detail-tabs [data-detail-tab={tab}]')
    expect(active).to_have_attribute('aria-pressed', 'true')

    def assert_selected_visible():
        assert active.evaluate('''(e)=>{
            const button=e.getBoundingClientRect(),nav=e.parentElement.getBoundingClientRect();
            return button.left>=Math.max(nav.left,0)-1 && button.right<=Math.min(nav.right,innerWidth)+1;
        }'''), f'Initial {tab} menu is clipped through {entry}'

    assert_selected_visible()
    # Users can browse earlier menus without selecting one; reopening must
    # bring the remembered selected menu back into view.
    page.locator('#detail-tabs').evaluate('(e)=>e.scrollLeft=0')
    page.locator('#close-work').click()
    page.locator('#filters [data-filter=all]').click()
    page.locator('[data-list-view=grid]').click()
    page.locator(f'[data-work="{work}"]').click()
    expect(active).to_have_attribute('aria-pressed', 'true')
    assert_selected_visible()


@pytest.mark.parametrize('state', ['completed', 'blocked'])
def test_selected_page_color_wins_over_completed_and_blocked_pipeline(studio_page, state):
    from playwright.sync_api import expect
    page, tasks = studio_page
    t = tasks[0]
    t['jobs'] = []
    if state == 'completed':
        t['status'] = 'completed'
        t['automation']['stage'] = 'completed'
        t['pipeline'][1]['status'] = 'completed'
        for step in t['pipeline'][1]['steps']:
            step['status'] = 'completed'
    else:
        t['status'] = 'failed'
        t['source_acquisition'] = dict(hold=True)
        t['pipeline'][1]['steps'][0]['status'] = 'blocked'
    prepare(page, tasks)
    for name in ['sources', 'script', 'voice', 'edit', 'results']:
        active = page.locator(f'#detail-tabs [data-detail-tab={name}]')
        active.click()
        expect(active).to_have_attribute('aria-pressed', 'true')
        page.wait_for_timeout(350)
        assert page.locator('#detail-tabs button').evaluate_all('(buttons)=>buttons.filter(b=>b.getAttribute("aria-pressed")!=="true").every(b=>getComputedStyle(b).backgroundColor!==getComputedStyle(buttons.find(x=>x.getAttribute("aria-pressed")==="true")).backgroundColor)')
