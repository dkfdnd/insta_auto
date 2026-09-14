"""웹 UI에서 소스 플랫폼의 전용 Chrome 로그인 세션을 관리한다."""
from __future__ import annotations

import threading
import time

from .browser_profile import BROWSER_LOCK, PLATFORMS, _platform_rows, export_cookies, profile_cookie_status
from .config import Settings


class PlatformSessionManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.active = False
        self.message = "저장된 로그인 상태"
        self.error = ""
        self.platforms = profile_cookie_status(settings.source_browser_profile_dir)

    def status(self) -> dict:
        with self.lock:
            if not self.active:
                self.platforms = profile_cookie_status(self.settings.source_browser_profile_dir)
            return {"active": self.active, "message": self.message, "error": self.error,
                    "platforms": list(self.platforms),
                    "cookie_file_ready": self.settings.source_browser_cookie_file.is_file()}

    def start(self) -> dict:
        with self.lock:
            if self.active:
                return self.status_unlocked()
            self.active = True
            self.message = "로그인용 Chrome을 여는 중"
            self.error = ""
            self.stop_event.clear()
        threading.Thread(target=self._work, daemon=True).start()
        return self.status()

    def finish(self) -> dict:
        self.stop_event.set()
        with self.lock:
            if self.active:
                self.message = "로그인 정보를 저장하는 중"
        return self.status()

    def status_unlocked(self) -> dict:
        return {"active": self.active, "message": self.message, "error": self.error,
                "platforms": list(self.platforms),
                "cookie_file_ready": self.settings.source_browser_cookie_file.is_file()}

    def _work(self) -> None:
        context = None
        try:
            from playwright.sync_api import sync_playwright
            with BROWSER_LOCK, sync_playwright() as pw:
                context = pw.chromium.launch_persistent_context(
                    str(self.settings.source_browser_profile_dir), channel="chrome", headless=False,
                    locale="ko-KR", viewport={"width": 1280, "height": 900},
                    args=["--disable-blink-features=AutomationControlled"],
                    ignore_default_args=["--enable-automation"],
                )
                pages = context.pages
                for index, spec in enumerate(PLATFORMS.values()):
                    page = pages[0] if index == 0 and pages else context.new_page()
                    try:
                        page.goto(spec["url"], wait_until="domcontentloaded", timeout=60000)
                    except Exception:  # 페이지별 차단은 다른 로그인 탭을 막지 않는다.
                        pass
                deadline = time.time() + 900
                while not self.stop_event.wait(2) and time.time() < deadline:
                    try:
                        cookies = context.cookies()
                        export_cookies(cookies, self.settings.source_browser_cookie_file)
                        platforms = _platform_rows(cookies)
                    except Exception:
                        break
                    with self.lock:
                        self.platforms = platforms
                        connected = sum(item["connected"] for item in platforms)
                        self.message = f"로그인 창 사용 중 · {connected}/{len(platforms)}개 연결 감지"
                try:
                    cookies = context.cookies()
                    export_cookies(cookies, self.settings.source_browser_cookie_file)
                    with self.lock:
                        self.platforms = _platform_rows(cookies)
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001
            with self.lock:
                self.error = f"Chrome 로그인 창 실행 실패: {type(exc).__name__}: {str(exc)[:220]}"
        finally:
            if context:
                try:
                    context.close()
                except Exception:
                    pass
            with self.lock:
                self.active = False
                self.message = "로그인 정보 저장 완료" if not self.error else "로그인 창 실행 실패"
