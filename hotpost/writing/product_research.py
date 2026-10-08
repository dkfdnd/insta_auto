"""Bounded, source-linked product facts. Research never retrieves video assets."""
import json
from urllib.parse import urlparse

from . import codex_writer
from ..request_pacing import request_pause

SCHEMA = {'type':'object', 'properties':{
    'facts':{'type':'array','maxItems':8, 'items':{'type':'object','properties':{
        'text':{'type':'string','maxLength':500}, 'source_url':{'type':'string'},
        'source_title':{'type':'string'}, 'same_product':{'type':'boolean'}},
        'required':['text','source_url','source_title','same_product'],'additionalProperties':False}},
    'warnings':{'type':'array','items':{'type':'string'}}},
    'required':['facts','warnings'], 'additionalProperties':False}


def research(payload, folder, check, progress):
    cached = folder/'product-facts.json'
    if cached.is_file():
        return json.loads(cached.read_text('utf-8'))
    progress(.2, '제품 정보와 출처 확인 중')
    request_pause()
    state = {'directory':folder, 'calls':[]}
    result = codex_writer.chat(
        '제품 또는 주제의 사실만 조사하세요. 영상 검색·다운로드를 하지 마세요. '
        '제공 링크가 있으면 해당 제품의 공식 페이지 또는 제조사·판매처 상세 설명을 우선하세요. '
        '최대 3번 검색하고 최대 3개 페이지를 확인하세요. CAPTCHA·로그인·접근 차단을 만나면 우회·반복하지 마세요. '
        '원문에서 실제 확인한 기능·사용 방법만 최대 8개 반환하세요. 모델·규격이 다른 제품을 같은 제품으로 간주하지 마세요. '
        '제품명이 모호하거나 해당 사실의 출처와 제품 일치가 확인되지 않으면 facts에서 빼고 warnings로 남기세요. '
        '검색 결과 문구·홍보성 효능·추측·가격·인기·후기를 사실로 승격하지 마세요. '
        '각 사실에 실제 열어 확인한 source_url과 source_title을 붙이세요. same_product가 true인 사실만 사용됩니다.',
        json.dumps(payload, ensure_ascii=False), SCHEMA, check, state, timeout=300, allow_web=True)
    result['facts'] = [f for f in result['facts'] if f['same_product'] and f['text'].strip()
                       and urlparse(f['source_url']).scheme in {'http','https'} and urlparse(f['source_url']).hostname]
    result['inference'] = {'provider':'codex', 'calls':state['calls'], 'fallback':False}
    cached.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    return result
