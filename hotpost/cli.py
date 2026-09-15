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
import json
import sys
import time
import webbrowser
import fcntl
from pathlib import Path

from .config import load_settings, Settings
from .storage import Storage
from .accounts import AccountRegistry


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


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
    for i, name in enumerate(usernames, 1):
        _log(f"[{i}/{len(usernames)}] @{name} 수집 중...")
        try:
            existing = {p.shortcode: p for p in store.posts_for(name, limit=settings.posts_per_account * 2)}
            profile, posts = collector.fetch(name, settings.posts_per_account, existing=existing)
        except CollectError as e:
            failed += 1
            notes.append(f"@{name}: {e}")
            _log(f"    실패: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            failed += 1
            notes.append(f"@{name}: 예기치 못한 오류 {type(e).__name__}: {e}")
            _log(f"    실패(예외): {type(e).__name__}: {e}")
            continue
        store.upsert_profile(profile)
        store.upsert_posts(posts)
        ok += 1
        total += len(posts)
        _log(f"    {len(posts)}개 게시물 (팔로워 {profile.followers:,})")
        if source != "demo" and i < len(usernames):
            time.sleep(settings.sleep_between_accounts)
    store.record_run(started, source, ok, failed, total, "\n".join(notes))
    return ok, failed, total, notes


def cmd_run(settings: Settings, args) -> int:
    lock_path = settings.data_dir / "collect.lock"
    lock_file = lock_path.open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        _log("다른 수집 작업이 이미 실행 중입니다.")
        return 3
    try:
        return _cmd_run_locked(settings, args)
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


def _cmd_run_locked(settings: Settings, args) -> int:
    from .report import build_report, write_report
    usernames = AccountRegistry(settings).usernames()
    if not usernames:
        _log("관리 중인 계정이 없습니다. 웹의 계정 관리 페이지에서 먼저 등록하세요.")
        return 2
    if args.only:
        usernames = [u for u in usernames if u in set(args.only)]
    db = settings.data_dir / "demo.db" if args.source == "demo" else settings.db_path
    store = Storage(db)
    ok, failed, total, notes = collect(settings, store, args.source, usernames)
    _log(f"수집 완료: 성공 {ok} / 실패 {failed} / 게시물 {total}")
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
    from .server import serve
    port = getattr(args, "port", 8765)
    httpd = serve(settings, port)
    url = f"http://localhost:{port}/"
    _log(f"웹페이지: {url}  (Ctrl+C 로 종료)")
    if not getattr(args, "no_browser", False):
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
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
    ap = argparse.ArgumentParser(prog="hotpost", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("run", help="수집 + 분석 + 리포트")
    p.add_argument("--source", default="web", choices=["web", "instaloader", "demo"])
    p.add_argument("--only", nargs="*", help="특정 계정만 수집")
    p.add_argument("--serve", action="store_true", help="완료 후 웹서버 실행")
    p.add_argument("--port", type=int, default=8765)
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
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("sources", help="릴스 장면을 분석해 공개 소스 영상 후보 탐색·다운로드")
    p.add_argument("shortcode", help="Instagram 릴스 shortcode (예: Dcp3P-WyMFe)")
    p.set_defaults(fn=cmd_sources)

    p = sub.add_parser("schedule", help="macOS 매일 자동 수집 일정 관리")
    p.add_argument("action", choices=["install", "status", "uninstall"])
    p.add_argument("--hour", type=int, default=7)
    p.add_argument("--minute", type=int, default=0)
    p.set_defaults(fn=cmd_schedule)

    p = sub.add_parser("list", help="인플루언서 목록 확인")
    p.set_defaults(fn=cmd_list)

    args = ap.parse_args(argv)
    settings = load_settings()
    sys.exit(args.fn(settings, args))
