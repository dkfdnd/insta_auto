"""명령행 진입점.

  python -m hotpost run                 # 수집 + 분석 + 리포트 (기본: 웹 GraphQL 수집기, 로그인 세션 필요)
  python -m hotpost run --source instaloader   # instaloader 수집기 사용
  python -m hotpost run --source demo   # 샘플 데이터로 전체 흐름 실행
  python -m hotpost login --user ID     # 인스타 로그인 후 세션 저장 (비밀번호는 터미널에서 직접 입력)
  python -m hotpost login --user ID --browser chrome   # 브라우저 쿠키로 세션 저장
  python -m hotpost import dump.json    # 브라우저 덤프(tools/browser_dump.js) 가져오기
  python -m hotpost analyze             # DB 에 있는 데이터로 리포트만 다시 생성
  python -m hotpost serve               # 웹페이지 열기 (http://localhost:8765)
  python -m hotpost list                # 인플루언서 목록 파싱 결과 확인
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import sys
import threading
import time
import webbrowser
import logging
import random
from logging.handlers import RotatingFileHandler
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

from .config import load_settings, Settings
from .storage import Storage
from .accounts import AccountRegistry


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _operational_event(settings: Settings, message: str) -> None:
    logger = logging.getLogger(f"hotpost.operational.{settings.data_dir.resolve()}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(settings.data_dir / "operational.log",
                                      maxBytes=max(1, settings.operational_log_max_mb) * 1024 * 1024,
                                      backupCount=max(1, settings.operational_log_backups), encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    logger.info(message)


def _safe_log_text(value: object, limit: int = 500) -> str:
    """운영 로그 한 줄을 유지하고 과도한 예외 본문은 잘라낸다."""
    return " ".join(str(value).split())[:limit]


def _sleep_after_account(settings: Settings, source: str, username: str,
                         outcome: str, has_next: bool) -> float:
    """성공·실패와 무관하게 다음 계정 전에 무작위 간격을 둔다."""
    if source == "demo" or not has_next:
        return 0.0
    if outcome == "failure":
        low = max(0.0, settings.sleep_after_error_min)
        high = max(low, settings.sleep_after_error_max)
    else:
        low = max(0.0, settings.sleep_between_accounts)
        high = max(low, settings.sleep_between_accounts_max)
    delay = random.uniform(low, high)
    _log(f"    다음 계정 전 {delay:.1f}초 대기 ({outcome})")
    _operational_event(settings, f"계정 간 대기 username=@{username} outcome={outcome} seconds={delay:.2f}")
    time.sleep(delay)
    return delay


# ------------------------------------------------------------------ commands

def cmd_list(settings: Settings, args) -> int:
    names = AccountRegistry(settings).usernames()
    print(f"{len(names)}개 관리 계정 (SQLite)")
    for n in names:
        print(" -", n)
    return 0


def cmd_login(settings: Settings, args) -> int:
    from .collectors.instaloader_collector import login_with_password, login_from_browser
    from .collectors.base import CollectError
    user = args.user or settings.ig_user
    try:
        if args.browser:
            f = login_from_browser(settings, user, args.browser)
        else:
            if not user:
                _log("--user 로 인스타 아이디를 지정하세요.")
                return 2
            f = login_with_password(settings, user)
    except CollectError as e:
        _log(f"로그인 실패: {e}")
        return 1
    _log(f"세션 저장 완료: {f}")
    _log("이제 `python -m hotpost run` 으로 실제 데이터를 수집할 수 있습니다.")
    return 0


def collect(settings: Settings, store: Storage, source: str, usernames: list[str]) -> tuple[int, int, int, list[str]]:
    from .collectors import get_collector
    from .collectors.base import CollectError
    collector = get_collector(source, settings)
    ok = failed = total = 0
    notes: list[str] = []
    started = int(time.time())
    run_id = store.start_run(started, source)
    for i, name in enumerate(usernames, 1):
        account_started = time.monotonic()
        _log(f"[{i}/{len(usernames)}] @{name} 수집 중...")
        try:
            existing = {p.shortcode: p for p in store.posts_for(name, limit=settings.posts_per_account * 2)}
            tracked = store.tracked_hot_posts(name, limit=settings.hot_view_tracking_limit)
            profile, posts, observations = collector.fetch(name, settings.collect_posts_per_account, existing=existing)
            fresh_codes = {post.shortcode for post in posts}
            tracked_extra = [post for post in tracked if post.shortcode not in fresh_codes]
            if tracked_extra and hasattr(collector, "refresh_video_views"):
                observations.extend(collector.refresh_video_views(tracked_extra, settings.hot_view_tracking_limit))
                posts.extend(tracked_extra)
                _log(f"    터진 릴스 조회수 추적 {len(tracked_extra)}개")
        except CollectError as e:
            failed += 1
            health = store.record_account_collection(name, False, "수집 오류")
            if health["consecutive_failures"] >= 3:
                store.notify("collection_failures", f"fail-{name}-{health['consecutive_failures']}",
                             f"@{name} 연속 수집 실패 {health['consecutive_failures']}회")
            if any(word in str(e).lower() for word in ("session", "세션", "login", "로그인")):
                store.notify("instagram_session", f"session-{int(time.time()) // 86400}",
                             "Instagram 세션을 확인해 주세요")
            notes.append(f"@{name}: {e}")
            _log(f"    실패: {e}")
            _operational_event(
                settings,
                f"계정 수집 실패 username=@{name} elapsed_ms={int((time.monotonic() - account_started) * 1000)} "
                f"error_type={type(e).__name__} error={_safe_log_text(e)}",
            )
            _sleep_after_account(settings, source, name, "failure", i < len(usernames))
            continue
        except Exception as e:  # noqa: BLE001
            failed += 1
            store.record_account_collection(name, False, type(e).__name__)
            notes.append(f"@{name}: 예기치 못한 오류 {type(e).__name__}: {e}")
            _log(f"    실패(예외): {type(e).__name__}: {e}")
            _operational_event(
                settings,
                f"계정 수집 실패 username=@{name} elapsed_ms={int((time.monotonic() - account_started) * 1000)} "
                f"error_type={type(e).__name__} error={_safe_log_text(e)}",
            )
            _sleep_after_account(settings, source, name, "failure", i < len(usernames))
            continue
        prior_missing = store.account_observation_health(name)["views_missing_rate"]
        store.upsert_profile(profile)
        store.upsert_posts(posts, observations=observations)
        store.record_account_collection(name, True)
        if any(o.http_status == 429 for o in observations):
            store.notify("instagram_429", f"429-{name}-{int(time.time()) // 86400}",
                         f"@{name} Instagram 조회 요청이 429 제한을 받았습니다")
        current_missing = store.account_observation_health(name)["views_missing_rate"]
        if current_missing >= .3 and current_missing - prior_missing >= .15:
            store.notify("views_missing_spike", f"missing-{name}-{int(time.time()) // 86400}",
                         f"@{name} 조회수 누락률이 {round(current_missing * 100)}%로 증가했습니다")
        ok += 1
        total += len(posts)
        _log(f"    {len(posts)}개 게시물 (팔로워 {profile.followers:,})")
        _operational_event(
            settings,
            f"계정 수집 성공 username=@{name} elapsed_ms={int((time.monotonic() - account_started) * 1000)} "
            f"posts={len(posts)} observations={len(observations)}",
        )
        _sleep_after_account(settings, source, name, "success", i < len(usernames))
    store.finish_run(run_id, ok, failed, total, "\n".join(notes))
    if failed:
        store.notify("collection_run", f"run-{started}",
                     f"수집 {'전체 실패' if ok == 0 else '부분 실패'} · 성공 {ok}계정 / 실패 {failed}계정")
    store.finalize_hot_tracking()
    return ok, failed, total, notes


def cmd_run(settings: Settings, args) -> int:
    lock_path = settings.data_dir / "collect.lock"
    lock_file = lock_path.open("a+b")
    try:
        if os.name == "nt":
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        lock_file.close()
        if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            raise
        _log("다른 수집 작업이 이미 실행 중입니다.")
        return 3
    try:
        return _cmd_run_locked(settings, args)
    finally:
        try:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
        finally:
            lock_file.close()


def _cmd_run_locked(settings: Settings, args) -> int:
    from .report import build_report, write_report
    usernames = AccountRegistry(settings).usernames()
    _operational_event(settings, "수집 실행 시작")
    if not usernames:
        _log("관리 중인 계정이 없습니다. 웹의 계정 관리 페이지에서 먼저 등록하세요.")
        return 2
    if args.only:
        usernames = [u for u in usernames if u in set(args.only)]
    db = settings.data_dir / "demo.db" if args.source == "demo" else settings.db_path
    store = Storage(db)
    ok, failed, total, notes = collect(settings, store, args.source, usernames)
    _log(f"수집 완료: 성공 {ok} / 실패 {failed} / 게시물 {total}")
    _operational_event(settings, f"수집 완료 성공={ok} 실패={failed} 게시물={total}")
    if ok == 0 and args.source != "demo":
        _log("수집된 계정이 없어 리포트를 만들지 않습니다. (세션 만료/차단 여부를 확인하세요)")
        return 1
    report = build_report(settings, store, source=args.source, notes=notes, usernames=usernames)
    write_report(settings, report)
    _log(f"리포트 생성: {settings.report_path}  (핫 게시물 {report['summary']['hot']}개 / 전체 {report['summary']['posts']}개)")
    if args.serve:
        return cmd_serve(settings, args)
    return 0


def cmd_schedule(settings: Settings, args) -> int:
    from .scheduler import install_schedule, schedule_status, uninstall_schedule
    try:
        if args.action == "install":
            status = install_schedule(settings, args.hour, args.minute)
        elif args.action == "uninstall":
            status = uninstall_schedule()
        else:
            status = schedule_status()
    except (RuntimeError, ValueError) as exc:
        _log(str(exc)); return 1
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


def cmd_import(settings: Settings, args) -> int:
    from .collectors.dump import load_dump
    from .report import build_report, write_report
    store = Storage(settings.db_path)
    started = int(time.time())
    total = 0
    data = load_dump(Path(args.file))
    for profile, posts in data:
        AccountRegistry(settings).add(profile.username)
        store.upsert_profile(profile)
        store.upsert_posts(posts)
        total += len(posts)
        _log(f"@{profile.username}: {len(posts)}개")
    store.record_run(started, "dump", len(data), 0, total, f"file={args.file}")
    report = build_report(settings, store, source="dump", usernames=AccountRegistry(settings).usernames())
    write_report(settings, report)
    _log(f"임포트 완료: 계정 {len(data)} / 게시물 {total} → 리포트 갱신")
    return 0


def cmd_analyze(settings: Settings, args) -> int:
    from .report import build_report, write_report
    store = Storage(settings.db_path)
    last = store.last_run()
    source = (last or {}).get("source") or "unknown"
    report = build_report(settings, store, source=source, usernames=AccountRegistry(settings).usernames())
    write_report(settings, report)
    _log(f"리포트 재생성: 핫 {report['summary']['hot']} / 전체 {report['summary']['posts']}")
    return 0


def cmd_serve(settings: Settings, args) -> int:
    from .server import serve_many
    port = getattr(args, "port", 8765)
    hosts = getattr(args, "hosts", None) or ["127.0.0.1"]
    httpds = serve_many(settings, hosts, port)
    url = f"http://localhost:{port}/"
    _log(f"웹페이지: {url}  (Ctrl+C 로 종료)")
    _log("바인드: " + ", ".join(f"http://{host}:{port}/" for host in hosts))
    if not getattr(args, "no_browser", False):
        webbrowser.open(url)
    threads = [threading.Thread(target=httpd.serve_forever, daemon=True) for httpd in httpds[1:]]
    for thread in threads:
        thread.start()
    try:
        httpds[0].serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for httpd in httpds[1:]:
            httpd.shutdown()
        for httpd in httpds:
            httpd.server_close()
    return 0


def cmd_sources(settings: Settings, args) -> int:
    from .source_finder import find_sources

    def progress(message: str, percent: int) -> None:
        _log(f"[{percent:3d}%] {message}")
    try:
        result = find_sources(settings, args.shortcode, progress)
    except Exception as exc:  # noqa: BLE001
        _log(f"소스 영상 탐색 실패: {exc}")
        return 1
    print(json.dumps({"job_id": result["job_id"], "downloaded": result["downloaded"],
                      "zip_path": result["zip_path"], "candidates": result["candidates"]}, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> None:
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="hotpost", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="수집 + 분석 + 리포트")
    p.add_argument("--source", default="web", choices=["web", "instaloader", "demo"])
    p.add_argument("--only", nargs="*", help="특정 계정만 수집")
    p.add_argument("--serve", action="store_true", help="완료 후 웹서버 실행")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", dest="hosts", action="append", help="명시적 바인드 주소 (여러 번 지정 가능)")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("login", help="인스타 로그인 세션 저장")
    p.add_argument("--user", help="인스타 아이디")
    p.add_argument("--browser", help="chrome / firefox / safari / edge 등 브라우저 쿠키에서 가져오기")
    p.set_defaults(fn=cmd_login)

    p = sub.add_parser("import", help="브라우저 덤프 JSON 가져오기")
    p.add_argument("file")
    p.set_defaults(fn=cmd_import)

    p = sub.add_parser("analyze", help="DB 데이터로 리포트만 재생성")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("serve", help="웹페이지 서버")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", dest="hosts", action="append", help="명시적 바인드 주소 (여러 번 지정 가능)")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("sources", help="릴스 장면을 분석해 공개 소스 영상 후보 탐색·다운로드")
    p.add_argument("shortcode", help="Instagram 릴스 shortcode (예: Dcp3P-WyMFe)")
    p.set_defaults(fn=cmd_sources)

    p = sub.add_parser("schedule", help="Windows/macOS 매일 자동 수집 일정 관리")
    p.add_argument("action", choices=["install", "status", "uninstall"])
    p.add_argument("--hour", type=int, default=7)
    p.add_argument("--minute", type=int, default=0)
    p.set_defaults(fn=cmd_schedule)

    p = sub.add_parser("list", help="인플루언서 목록 확인")
    p.set_defaults(fn=cmd_list)

    args = ap.parse_args(argv)
    settings = load_settings()
    sys.exit(args.fn(settings, args))
