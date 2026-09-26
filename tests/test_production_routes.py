"""The upstream and pre-existing production APIs must never shadow each other."""
import json
import threading
from http.client import HTTPConnection
from types import SimpleNamespace

from hotpost.config import Settings


def test_integrated_and_legacy_production_routes_are_separate(tmp_path, monkeypatch):
    from hotpost import server

    registered = {}
    queue = SimpleNamespace(register=lambda key, work: registered.update({key: work}),
                            resume_queued=lambda: None)
    monkeypatch.setattr(server, "JobQueue", lambda settings: queue)
    for name in ("SourceJobManager", "TranscriptJobManager", "PlatformSessionManager",
                 "AccountRegistry"):
        monkeypatch.setattr(server, name, lambda *args: SimpleNamespace())
    legacy = SimpleNamespace(list=lambda: [{"shortcode": "old-reel"}])
    monkeypatch.setattr(server, "LegacyProductionManager", lambda *args: legacy)
    modern = SimpleNamespace(
        listing=lambda: [{"id": "new-job"}],
        create=lambda payload: {"id": "created", "product": payload["product"]},
        dispatch=lambda job, action: {"id": job, "action": action})
    monkeypatch.setattr(server, "ProductionManager", lambda settings: modern)
    studio = SimpleNamespace(store=SimpleNamespace(list=lambda: [{"id": "studio-job"}]),
                             public=lambda job: job, create=lambda code: {"shortcode": code})
    monkeypatch.setattr(server, "Studio", lambda settings: studio)
    httpd = server.serve(Settings(data_dir=tmp_path), port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    conn = HTTPConnection(*httpd.server_address, timeout=3)
    try:
        for route, expected in (
            ("/api/productions", {"items": [{"id": "new-job"}]}),
            ("/api/legacy-productions", {"enabled": False, "productions": [{"shortcode": "old-reel"}]}),
            ("/api/studio", {"tasks": [{"id": "studio-job"}]}),
        ):
            conn.request("GET", route)
            response = conn.getresponse()
            assert response.status == 200
            assert json.loads(response.read()) == expected
        for route, body, expected in (
            ("/api/productions", {"product": "bag"}, {"id": "created", "product": "bag"}),
            ("/api/productions/new-job/build", {}, {"id": "new-job", "action": "build"}),
        ):
            conn.request("POST", route, body=json.dumps(body),
                         headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            assert response.status == 202
            assert json.loads(response.read()) == expected
        assert registered["production"]("old-reel", None) == {
            "studio": {"shortcode": "old-reel"}}
    finally:
        conn.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
