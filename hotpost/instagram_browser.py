"""로그인과 수집이 함께 쓰는 전용 영속 브라우저. 비밀값을 로그에 남기지 않는다."""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from .collectors.base import CollectionBlocked, CollectError


class InstagramBrowser:
    def __init__(self, settings):
        self.settings = settings
        self.context = self.page = self.pw = self.lock = None

    def open(self):
        from playwright.sync_api import sync_playwright
        folder = self.settings.data_dir / 'instagram_browser'
        folder.mkdir(parents=True, exist_ok=True)
        self.lock = (self.settings.data_dir / 'instagram_browser.lock').open('a+b')
        try:
            self.lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            self.lock = None
            raise CollectionBlocked('profile_busy', '전용 Instagram 브라우저를 다른 작업이 사용 중입니다.') from exc
        try:
            self.pw = sync_playwright().start()
            self.context = self.pw.chromium.launch_persistent_context(
                str(folder), channel='chrome', headless=False, locale='ko-KR',
                viewport={'width': 1200, 'height': 850},
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.set_default_timeout(15000)
            return self
        except Exception as exc:
            self.close()
            raise CollectionBlocked('browser_unavailable', '전용 Chrome을 시작하지 못했습니다. 프로필 사용 상태를 확인하세요.') from exc

    def guard(self):
        path = urlsplit(self.page.url).path.lower()
        if any(p in path for p in ('/challenge', '/checkpoint', '/two_factor', '/consent')):
            raise CollectionBlocked('verification_required', 'Instagram 계정 확인이 필요합니다. 전용 로그인 창에서 인증하세요.')
        if '/accounts/login' in path:
            raise CollectionBlocked('login_required', '전용 Instagram 브라우저에 로그인이 필요합니다.')
        text = self.page.locator('body').inner_text(timeout=10000).lower()
        if any(p in text for p in ('죄송합니다. 페이지를 사용할 수 없습니다.',
                                  "sorry, this page isn't available.")):
            raise CollectError('Instagram에서 페이지를 사용할 수 없다고 표시합니다. 계정명 변경·삭제·접근 상태를 확인하세요.')
        if any(p in text for p in ('confirm it', '자동화된 활동', 'automated behavior', '계정을 보호', '본인 확인')):
            raise CollectionBlocked('verification_required', 'Instagram 계정 확인 안내가 표시되어 수집을 중단했습니다.')
        if any(p in text for p in ('try again later', '나중에 다시 시도', '잠시 후 다시', '일부 활동을 제한', 'we restrict certain activity')):
            raise CollectionBlocked('rate_limited', 'Instagram 요청 제한 안내가 표시되어 수집을 중단했습니다.')

    def navigate(self, path):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout, Error
        try:
            response = self.page.goto('https://www.instagram.com/' + path.lstrip('/'),
                                      wait_until='domcontentloaded', timeout=45000)
        except PlaywrightTimeout as exc:
            raise CollectionBlocked('network_timeout', 'Instagram 페이지 응답 시간이 초과되었습니다.') from exc
        except Error as exc:
            reason = 'redirect_loop' if 'ERR_TOO_MANY_REDIRECTS' in str(exc) else 'browser_navigation'
            raise CollectionBlocked(reason, 'Instagram 브라우저 탐색에 실패했습니다. 자동 반복 요청을 중단합니다.') from exc
        if response and response.status in (401, 403, 429):
            reason = 'rate_limited' if response.status == 429 else 'access_denied'
            raise CollectionBlocked(reason, f'Instagram HTTP {response.status}: 수집을 중단했습니다.')
        if response and response.status == 404:
            raise CollectError('Instagram 프로필 또는 게시물을 찾을 수 없습니다.')
        if response and response.status >= 500:
            raise CollectionBlocked('server_error', 'Instagram 서버 오류로 수집을 중단했습니다.')
        self.page.wait_for_timeout(1500)
        self.guard()

    def verify_identity(self):
        if not self.settings.ig_user:
            raise CollectionBlocked('configuration', '수집용 Instagram 계정 설정이 필요합니다.')
        self.guard()
        name = self.settings.ig_user.lower()
        # 프로필 내 태그/게시물 소유자 링크가 아니라 로그인 사용자 탐색 메뉴의 프로필 사진.
        for _ in range(8):
            self.guard()
            verified = self.page.evaluate('''name => Array.from(document.querySelectorAll('a[href="/' + name + '/"] img'))
                .some(img => !img.closest('main') && (img.alt || '').toLowerCase().includes(name))''', name)
            if verified:
                return
            self.page.wait_for_timeout(1000)
        raise CollectionBlocked('login_required', '전용 브라우저에서 설정된 수집용 계정의 로그인을 확인하지 못했습니다.')

    def close(self):
        try:
            if self.context:
                self.context.close()
        finally:
            self.context = self.page = None
            try:
                if self.pw:
                    self.pw.stop()
            finally:
                self.pw = None
                if self.lock:
                    self.lock.close()
                    self.lock = None
