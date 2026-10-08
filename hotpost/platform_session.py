"""웹 UI에서 소스 플랫폼의 전용 Chrome 로그인 세션을 관리한다."""
from __future__ import annotations

import threading
import time
import json
from contextlib import ExitStack
from urllib.parse import urlparse

from .browser_profile import BROWSER_LOCK, PLATFORMS, _platform_rows, profile_cookie_status, probe_platform_auth, save_platform_cookies, restore_platform_cookies, source_context_options
from .search_access import PROVIDERS, access_record, manual_required, request_manual_recheck, challenge_on_page, login_wall_on_page
from .config import Settings
from .login_exchange import login_profile, publish_session, apply_sessions, read_session


class PlatformSessionManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.focus_event = threading.Event()
        self.active = False
        self.active_platform = None
        self.phase = 'idle'
        self.message = "저장된 로그인 상태"
        self.error = ""
        self.platforms = self._stored_rows()
        self.last_auth_checked_at = 0.0
        self.verification_result = None
        self.profile_role = 'login'

    def _stored_rows(self):
        source = profile_cookie_status(self.settings.source_browser_profile_dir)
        instagram = profile_cookie_status(self.settings.data_dir / 'instagram_browser')
        rows = {p['id']:p for p in source if p['id'] != 'instagram'}
        rows.update({p['id']:p for p in instagram if p['id'] == 'instagram'})
        for key in PLATFORMS:
            try:
                saved = json.loads((self.settings.data_dir/'platform_sessions'/f'{key}.json').read_text(encoding='utf-8'))
                present = next(p for p in _platform_rows(saved.get('cookies',[])) if p['id']==key)['cookie_present']
                rows[key]['cookie_present'] = rows[key]['cookie_present'] or present
            except (OSError, ValueError, TypeError): pass
            saved = read_session(self.settings.data_dir, key)
            if saved:
                present = next(p for p in _platform_rows(saved.get('cookies', [])) if p['id'] == key)['cookie_present']
                rows[key]['cookie_present'] = rows[key]['cookie_present'] or present
        return [rows[key] for key in PLATFORMS]

    def _save_cookies(self, cookies, instagram=False):
        for key in ([self.active_platform] if self.active_platform else PLATFORMS):
            if (key == 'instagram') != instagram: continue
            if instagram:
                save_platform_cookies(cookies, self.settings.data_dir, key)
            else:
                publish_session(cookies, self.settings.data_dir, key)

    def _update_rows(self, cookies, checks=None, instagram=False):
        rows = {p['id']: p for p in self.platforms}
        for p in _platform_rows(cookies, checks):
            if ((p['id'] == 'instagram') == instagram
                    and (not self.active_platform or p['id'] == self.active_platform)):
                rows[p['id']] = p
        self.platforms = [rows[key] for key in PLATFORMS]

    def status(self) -> dict:
        with self.lock:
            if not self.active and time.time() - self.last_auth_checked_at > 600:
                self.platforms = self._stored_rows()
            return self.status_unlocked()

    def start(self, platform=None, verification_query=None) -> dict:
        if platform is not None and (not isinstance(platform, str) or platform not in PLATFORMS):
            raise ValueError('지원하지 않는 플랫폼입니다.')
        verification = None
        if verification_query is not None:
            if platform != 'tiktok':
                raise ValueError('검색 인증 확인은 TikTok에서만 지원합니다.')
            from .platform_verification import TikTokSearchVerification
            verification = TikTokSearchVerification(verification_query)
        with self.lock:
            if self.active:
                if platform != self.active_platform:
                    raise ValueError('열려 있는 로그인 창에서 세션 저장 완료를 누른 뒤 다른 플랫폼을 여세요.')
                self.focus_event.set()
                return self.status_unlocked()
            self.active = True
            self.active_platform = platform
            self.phase = 'opening'
            self.message = f"{PLATFORMS[platform]['label'] if platform else '소스 플랫폼'} 로그인용 Chrome을 여는 중"
            self.error = ""
            self.verification_result = None
            self.profile_role = 'login'
            self.stop_event.clear()
            self.focus_event.clear()
        try:
            threading.Thread(target=self._work, args=(platform, verification), daemon=True).start()
        except Exception:
            with self.lock:
                self.active = False
                self.active_platform = None
                self.phase = 'idle'
            raise
        return self.status()

    def finish(self) -> dict:
        self.stop_event.set()
        with self.lock:
            if self.active:
                self.message = "로그인 정보를 저장하는 중"
        return self.status()

    def status_unlocked(self) -> dict:
        rows=[dict(row) for row in self.platforms]
        for row in rows:
            gate=access_record(self.settings.data_dir,PROVIDERS.get(row['id'],row['id']))
            if manual_required(gate):
                row.update(connected=False,auth_status='login_required' if gate.get('reason')=='login_required' else 'verification_required')
        return {"active": self.active, "active_platform": self.active_platform, "phase": self.phase, "message": self.message, "error": self.error,
                "platforms": rows,
                "verification_result": self.verification_result, "profile_role": self.profile_role,
                "cookie_file_ready": self.settings.source_browser_cookie_file.is_file()}

    def _work(self, platform=None, verification=None) -> None:
        context = None
        browser = None
        instagram = platform == 'instagram'
        window_closed = False
        search_profile_owned = False
        try:
            from playwright.sync_api import sync_playwright
            with ExitStack() as stack:
                if instagram:
                    from .instagram_browser import InstagramBrowser
                    browser = InstagramBrowser(self.settings).open()
                    context = browser.context
                else:
                    pw = stack.enter_context(sync_playwright())
                    profile = login_profile(self.settings.data_dir, platform)
                    if verification:
                        # A regular login still opens asynchronously while search
                        # is busy. Search verification needs the actual source
                        # profile and never races an already-owned search.
                        search_profile_owned = BROWSER_LOCK.acquire(blocking=False)
                        if not search_profile_owned:
                            raise RuntimeError('수집 검색이 진행 중입니다. 검색 확인 창은 수집이 끝난 뒤 열어 주세요.')
                        profile = self.settings.source_browser_profile_dir
                        with self.lock: self.profile_role = 'collection'
                    context = pw.chromium.launch_persistent_context(
                        str(profile), **source_context_options(False),
                    )
                    targets = [platform] if platform else [key for key in PLATFORMS if key != 'instagram']
                    restore_platform_cookies(context, self.settings.data_dir, targets)
                    apply_sessions(context, self.settings.data_dir, profile, targets)
                pages = context.pages
                platform_pages={}
                keys = [platform] if platform else [key for key in PLATFORMS if key != 'instagram']
                for index, key in enumerate(keys):
                    spec = PLATFORMS[key]
                    page = pages[0] if index == 0 and pages else context.new_page()
                    platform_pages[key]=page
                    if verification: verification.attach(page)
                    if verification:
                        with self.lock: self.message = '수집 검색 화면 준비 중 · 기존 검색 간격을 지킵니다.'
                        time.sleep(max(1, min(60, self.settings.source_browser_search_interval)))
                    try:
                        page.goto(verification.url if verification else spec["url"], wait_until="domcontentloaded", timeout=60000)
                    except Exception:  # 페이지별 차단은 다른 로그인 탭을 막지 않는다.
                        pass
                    if hasattr(page, 'bring_to_front'): page.bring_to_front()
                deadline = time.time() + 600
                with self.lock:
                    self.phase = 'open'
                    self.message = '로그인 창에서 인증한 뒤 이 페이지의 세션 저장 완료를 누르세요.'
                next_observation = 0
                while not self.stop_event.wait(.5) and time.time() < deadline:
                    try:
                        if all(hasattr(p, 'is_closed') and p.is_closed() for p in platform_pages.values()):
                            window_closed = True
                            break
                        if self.focus_event.is_set():
                            self.focus_event.clear()
                            for page in platform_pages.values():
                                if hasattr(page, 'bring_to_front'): page.bring_to_front()
                        cookies = context.cookies()
                        self._save_cookies(cookies, instagram)
                        if verification and time.monotonic() >= next_observation:
                            try:
                                observed = verification.observe(platform_pages[platform])
                            except Exception:
                                observed = {'status':'loading', 'candidates':0}
                            with self.lock: self.verification_result = observed
                            next_observation = time.monotonic()+2
                    except Exception:
                        window_closed = True
                        break
                    with self.lock:
                        self._update_rows(cookies, instagram=instagram)
                        self.message = (verification.message(self.verification_result or {'status':'loading'}) if verification else
                                        '로그인 창에서 인증한 뒤 이 페이지의 세션 저장 완료를 누르세요.')
                try:
                    if window_closed:
                        try: context.close()
                        except Exception: pass
                        context = None
                        return
                    with self.lock: self.phase = 'saving'
                    cookies = context.cookies()
                    self._save_cookies(cookies, instagram)
                    checks = {}
                    if instagram:
                        try:
                            browser.verify_identity(); checks['instagram'] = 'authenticated'
                        except Exception:
                            checks['instagram'] = 'unverified'
                    else:
                        with self.lock: self.message = '세션 저장 완료 · 로그인 유효성을 확인하는 중'
                        for key in keys:
                            provider=PROVIDERS.get(key,key)
                            if verification:
                                # The loaded search is the check. Do not send an
                                # extra /login request or turn timeout into success.
                                observed = verification.observe(platform_pages[key])
                                with self.lock: self.verification_result = observed
                                checks[key] = ('verification_required' if observed['status']=='captcha' else
                                               'login_required' if observed['status']=='login_required' else 'unverified')
                                if (self.stop_event.is_set() and observed['status'] in {'results','no_results'} and
                                        any(p['id']==key and p['cookie_present'] for p in _platform_rows(cookies))):
                                    request_manual_recheck(self.settings.data_dir, provider)
                                continue
                            if manual_required(access_record(self.settings.data_dir,provider)):
                                # The explicit save click permits one access recheck,
                                # only after the visible challenge/login wall is gone.
                                page=platform_pages[key]
                                host=urlparse(page.url).hostname or ''
                                if (not self.stop_event.is_set() or not any(host==d or host.endswith('.'+d) for d in PLATFORMS[key]['domains'])
                                        or not page.locator('body').inner_text().strip() or challenge_on_page(page)):
                                    checks[key]='verification_required'
                                    continue
                                if login_wall_on_page(page,provider):
                                    checks[key]='login_required'
                                    continue
                                if key=='google' or any(p['id']==key and p['cookie_present'] for p in _platform_rows(cookies)):
                                    request_manual_recheck(self.settings.data_dir,provider)
                            if key=='google':
                                checks[key]='unverified'; continue
                            if not any(p['id'] == key and p['cookie_present'] for p in _platform_rows(cookies)):
                                checks[key] = 'login_required'; continue
                            time.sleep(max(1, self.settings.source_browser_search_interval))
                            checks[key] = probe_platform_auth(context, key)
                    with self.lock:
                        self._update_rows(cookies, checks, instagram)
                        self.last_auth_checked_at = time.time()
                except Exception as exc:
                    with self.lock:
                        self.error = f'세션 저장 또는 인증 확인 실패: {type(exc).__name__}. 로그인 창을 다시 열어 확인하세요.'
                # Close before leaving Playwright, so persistent profile writes finish.
                if browser:
                    browser.close(); browser = None
                else:
                    context.close()
                context = None
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.error = f"Chrome 로그인 창 실행 실패: {type(exc).__name__}: {str(exc)[:220]}"
        finally:
            if context:
                try:
                    if browser: browser.close()
                    else: context.close()
                except Exception:
                    pass
            if search_profile_owned:
                BROWSER_LOCK.release()
            with self.lock:
                self.active = False
                self.active_platform = None
                self.phase = 'idle'
                self.message = ('로그인 창이 닫혔습니다. 로그인 버튼을 누르면 바로 다시 열립니다.' if window_closed else
                    "세션 저장 완료 · 아래 플랫폼 상태를 확인하세요." if not self.error else "로그인 저장을 완료하지 못했습니다.")
                if verification and not window_closed and not self.error:
                    result = self.verification_result or {'status':'loading'}
                    self.message = ('검색 접근 확인 · 세션 저장 완료' if result['status'] in {'results','no_results'} and self.stop_event.is_set() else
                                    '검색 인증 확인이 끝나지 않아 자동 재검색을 허용하지 않았습니다.')
