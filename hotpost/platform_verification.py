"""Observe one user-requested search; never solve or retry authentication."""
from urllib.parse import parse_qs, quote_plus, urlparse

from .search_access import challenge_on_page, empty_results_on_page, login_wall_on_page
from .source_search.tiktok_results import search_response_candidates


class TikTokSearchVerification:
    def __init__(self, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 180:
            raise ValueError('검색어는 1~180자로 입력하세요.')
        self.query = ' '.join(query.split())
        self.url = 'https://www.tiktok.com/search/video?q=' + quote_plus(self.query)
        self.candidates = {}

    def attach(self, page):
        def receive(response):
            parsed = urlparse(response.url)
            if parsed.hostname not in {'www.tiktok.com', 'tiktok.com'} or parsed.path not in {
                    '/api/search/item/full/', '/api/search/general/full/'}:
                return
            try:
                for item in search_response_candidates(response.url, response.json(), self.query):
                    self.candidates[item['url']] = item
            except Exception:
                pass
        page.on('response', receive)

    def observe(self, page):
        parsed = urlparse(page.url)
        if parsed.hostname not in {'www.tiktok.com', 'tiktok.com'}:
            return {'status': 'loading', 'candidates': 0}
        if challenge_on_page(page):
            return {'status': 'captcha', 'candidates': 0}
        if login_wall_on_page(page, 'tiktok'):
            return {'status': 'login_required', 'candidates': 0}
        if (parsed.path != '/search/video' or
                parse_qs(parsed.query).get('q', [''])[0] != self.query):
            return {'status': 'page_changed', 'candidates': 0}
        if self.candidates:
            return {'status': 'results', 'candidates': len(self.candidates)}
        if empty_results_on_page(page):
            return {'status': 'no_results', 'candidates': 0}
        return {'status': 'loading', 'candidates': 0}

    @staticmethod
    def message(result):
        status = result['status']
        if status == 'captcha':
            return '검색 화면에 인증이 필요합니다. Chrome에서 직접 완료한 뒤 세션 저장 완료를 누르세요.'
        if status == 'login_required':
            return '검색 화면에서 로그인한 뒤 세션 저장 완료를 누르세요.'
        if status == 'results':
            return f"검색 결과 {result['candidates']}개 확인 · 확인을 마치면 세션 저장 완료를 누르세요."
        if status == 'no_results':
            return '검색은 정상 응답했지만 결과가 없습니다. 확인을 마치면 세션 저장 완료를 누르세요.'
        if status == 'page_changed':
            return '검색 확인 화면으로 돌아온 뒤 세션 저장 완료를 누르세요.'
        return '검색 화면 로딩을 기다리는 중 · 창을 유지합니다.'
