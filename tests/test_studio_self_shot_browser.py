import copy
import json

import pytest

from test_studio_board_browser import studio_page


@pytest.mark.parametrize('mobile',[False,True])
def test_self_shot_create_edit_upload_start_and_no_external_search(studio_page,mobile):
    from playwright.sync_api import expect
    page,tasks=studio_page
    if mobile:page.set_viewport_size({'width':390,'height':844})
    def create(route):
        body=route.request.post_data_json
        own=copy.deepcopy(tasks[0]);own.update(id='own-test',shortcode='own-'+'a'*32,title='내 대본 쇼츠',
            creation_mode='self_shot',self_shot={**body,'started':False},status='self_shot_draft',revision=1,
            sources=[],jobs=[],original_text='',scripts=[],script_id=None,latest_completed_run_id=None)
        own['automation'].update(active=False,stage='prepare');own['pipeline']=[]
        tasks.append(own)
        route.fulfill(status=202,content_type='application/json',body=json.dumps(own))
    page.route('**/api/studio/self-shot',create)
    page.locator('#new-self-shot').click()
    expect(page.get_by_role('dialog',name='새 쇼츠 만들기')).to_be_visible()
    page.locator('[name=product]').fill('접이식 도시락통')
    page.locator('.self-shot-extra summary').click()
    page.locator('[name=details]').fill('접어서 가방에 보관하는 편리함')
    page.locator('[data-own-close]').first.click()
    page.locator('#new-self-shot').click()
    expect(page.locator('[name=product]')).to_have_value('접이식 도시락통')
    page.locator('input[value=manual]').check()
    text='이 대본 그대로 읽어주세요!\n내가 만든 두 번째 문장입니다.'
    page.locator('[name=text]').fill(text)
    page.locator('[data-own-submit]').click()
    expect(page.locator('#drawer-code')).to_have_text('내 촬영 영상 → 우리 쇼츠 제작')
    expect(page.locator('[data-pf=search]')).to_have_count(0)
    expect(page.get_by_text('선택한 촬영 영상으로 제작 시작',exact=True)).to_be_disabled()
    page.locator('[data-upload-files]').set_input_files([
        {'name':'one.mov','mimeType':'video/quicktime','buffer':b'first'},
        {'name':'two.mp4','mimeType':'video/mp4','buffer':b'second'}])
    expect(page.locator('[data-upload-state=done]')).to_have_count(2)
    expect(page.locator('[data-field^="source:"]:checked')).to_have_count(2)
    page.locator('[data-field^="source:"]').last.uncheck()
    page.get_by_text('선택한 촬영 영상으로 제작 시작',exact=True).click()
    expect(page.locator('.pf-message')).to_contain_text('선택한 영상으로 제작을 이어갑니다')
    own=tasks[-1]
    assert own['self_shot']['text']==text
    assert len(own['_used_sources'])==1
    assert page.locator('.self-shot-dialog').evaluate('(el)=>!el.open')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_self_shot_draft_never_prompts_for_original_speech(studio_page):
    from playwright.sync_api import expect
    page,tasks=studio_page
    own=tasks[0];own.update(creation_mode='self_shot',self_shot={'started':False,'script_mode':'manual','text':'내 대본'},
                            status='self_shot_draft',jobs=[],sources=[],original_text='')
    own['automation']['active']=False;own['revision']+=1
    page.evaluate('refreshStudio()');page.locator('[data-work=source]').click()
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    expect(page.locator('[data-pf-section=script] .sd-script-text')).to_have_text('내 대본')
    expect(page.locator('[data-field=original]')).to_have_count(0)
    expect(page.locator('[data-pf=resume-auto]')).to_have_count(0)


def test_self_shot_automatic_form_dark_theme_and_required_product(studio_page):
    from playwright.sync_api import expect
    page,_=studio_page
    page.evaluate("document.documentElement.dataset.theme='dark'")
    page.locator('#new-self-shot').click()
    expect(page.locator('[data-own-auto]')).to_be_visible()
    expect(page.locator('[data-own-manual]')).to_be_hidden()
    assert page.locator('[name=product]').evaluate('(el)=>el.required')
    assert not page.locator('form').evaluate('(el)=>el.checkValidity()')
    colors=page.locator('.self-shot-dialog').evaluate('(el)=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color})')
    assert colors['background']=='rgb(29, 41, 60)' and colors['color']=='rgb(237, 243, 255)'
    page.locator('[name=product]').fill('접이식 도시락통')
    assert page.locator('form').evaluate('(el)=>el.checkValidity()')


def test_self_shot_result_displays_actual_reuse_and_product_evidence(studio_page):
    from playwright.sync_api import expect
    page,tasks=studio_page
    t=tasks[-1];t.update(creation_mode='self_shot',self_shot={'started':True,'script_mode':'automatic','product':'도시락통'},
        research={'facts':[{'text':'접어서 보관할 수 있어요.','source_url':'https://example.com/product','source_title':'제품 상세'}]},
        edit_id='owned-edit',edits=[{'id':'owned-edit','plan':{'shots':[], 'beats':[], 'cues':[],
            'warnings':['촬영 장면 재사용: 2개 구간에서 촬영 장면을 반복했습니다.']}}])
    t['pipeline'][-1]['artifacts']['edit_id']='owned-edit';t['revision']+=1
    page.evaluate('refreshStudio()');page.locator('[data-work=done]').click()
    expect(page.locator('[data-owned-reuse]')).to_contain_text('2개 구간')
    expect(page.locator('[data-download-asset=reference]')).to_have_count(0)
    page.locator('#detail-tabs [data-detail-tab=script]').click()
    page.get_by_role('button',name='제품 정보와 집필 근거 보기',exact=True).click()
    expect(page.get_by_role('link',name='제품 상세',exact=True)).to_have_attribute('href','https://example.com/product')
