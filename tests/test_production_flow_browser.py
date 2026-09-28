"""Browser regression coverage; skips on machines without Playwright/Chrome."""
from pathlib import Path

import pytest


def test_focused_version_selector_switches_preview():
    browser_api = pytest.importorskip('playwright.sync_api')
    with browser_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel='chrome', headless=True)
        except browser_api.Error as exc:
            pytest.skip(f'Chrome unavailable: {exc}')
        try:
            page = browser.new_page()
            page.route('http://studio.test/**', lambda route: route.fulfill(
                content_type='text/html', body='<div id="root"></div>'))
            page.goto('http://studio.test/')
            page.add_script_tag(path=str(Path(__file__).parents[1]/'web'/'production-flow.js'))
            page.evaluate("""() => ProductionFlow.mount(document.querySelector('#root'), {
                id:'work-test', run_id:'v2', latest_completed_run_id:'v2',
                automation:{protocol:2,active:true}, status:'completed', message:'Ready',
                pipeline:[1,2].map(n=>({id:'v'+n,number:n,status:'completed',
                    steps:[],artifacts:{},video_url:'/video-'+n+'.mp4'}))
            })""")
            selector = page.locator('[data-pf-version]')
            selector.focus()
            selector.select_option('v1')
            assert page.locator('.pf-summary > video').get_attribute('src') == '/video-1.mp4'
            selector.focus()
            selector.select_option('v2')
            assert page.locator('.pf-summary > video').get_attribute('src') == '/video-2.mp4'
        finally:
            browser.close()
