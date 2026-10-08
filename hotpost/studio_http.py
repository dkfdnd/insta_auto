"""Studio HTTP routes including byte ranges for precise audio/video seeking."""
import json
import mimetypes
import re
from urllib.parse import parse_qs, urlparse

from .studio_store import Conflict


class StudioHTTP:
    def studio_post(self, studio):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/studio"):
            return False
        try:
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                self._json({"error": "다른 사이트에서의 변경 요청은 허용되지 않습니다."}, 403); return True
            length = int(self.headers.get("Content-Length", "0"))
            parts = parsed.path.strip('/').split('/')
            if len(parts)==4 and parts[3]=='upload-source':
                if not 0 < length <= 512*1024*1024: raise ValueError('영상은 512MB 이하로 업로드하세요.')
                self._json(studio.upload_source(parts[2], self.rfile, length,
                    parse_qs(parsed.query).get('name',['source.mp4'])[0]), 202)
                return True
            if not 0 < length <= 100_000: raise ValueError("올바르지 않은 요청 크기")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict): raise ValueError("JSON 객체가 필요합니다.")
            parts = parsed.path.strip("/").split("/")
            if parts == ['api','studio','self-shot']:
                self._json(studio.create_self_shot(data), 202)
            elif len(parts) == 2:
                codes = data.get("shortcodes", [])
                if not isinstance(codes, list) or not 1 <= len(codes) <= 100:
                    raise ValueError("제작할 소재를 선택하세요. 한 번에 최대 100개씩 추가할 수 있습니다.")
                if data.get('only_new'):
                    results = [studio.create(str(code), with_created=True) for code in dict.fromkeys(codes)]
                    tasks = [studio.action(t['id'],'start-auto',{}) if created and data.get('automatic') else t
                             for t,created in results]
                else:
                    tasks = [studio.create(str(code)) for code in dict.fromkeys(codes)]
                    if data.get('automatic'):
                        tasks = [studio.action(t['id'],'start-auto',{}) for t in tasks]
                self._json({"tasks":tasks}, 202)
            elif len(parts) == 4:
                self._json(studio.action(parts[2], parts[3], data), 202)
            else:
                self._json({"error": "경로를 찾을 수 없습니다."}, 404)
        except Conflict as exc:
            self._json({"error": str(exc)}, 409)
        except (ValueError, KeyError, StopIteration, TypeError) as exc:
            self._json({"error": str(exc) or "요청한 버전을 찾을 수 없습니다."}, 400)
        except RuntimeError as exc:
            self._json({'error':str(exc)},503)
        return True

    def studio_get(self, studio):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/studio"):
            return False
        try:
            parts = parsed.path.strip("/").split("/")
            if parts == ['api','studio','intake']:
                from .studio_intake import intake_status
                self._json(intake_status(studio))
            elif parts == ['api','studio','voices']:
                from .voicebench_adapter import VoiceBenchAdapter
                data=VoiceBenchAdapter(studio.settings).voices()
                readiness=VoiceBenchAdapter(studio.settings).default_voice_status()
                data['personal_default']={'available':bool(readiness.get('ready') and readiness.get('default_voice_kind')=='personal'),
                                          'errors':readiness.get('errors',[])}
                for voice in data.get('voices',[]):
                    if voice.get('preview_url'): voice['preview_url']='/api/studio/voices/'+voice['id']+'/preview'
                self._json(data)
            elif len(parts)==5 and parts[:3]==['api','studio','voices'] and parts[4]=='preview':
                from .voicebench_adapter import VoiceBenchAdapter
                content,mime=VoiceBenchAdapter(studio.settings).preview(parts[3])
                self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(content)))
                self.send_header('Cache-Control','private, max-age=300');self.end_headers();self.wfile.write(content)
            elif len(parts) == 2:
                self._json({"tasks": [studio.public(s) for s in studio.store.list()]})
            elif len(parts) == 3:
                self._json(studio.public(studio.store.get(parts[2])))
            elif len(parts) == 4 and parts[3] == "media":
                target = studio.media(parts[2], parse_qs(parsed.query).get("file", [""])[0])
                self._studio_stream(target)
            elif len(parts)==4 and parts[3]=='download':
                query = parse_qs(parsed.query)
                target = studio.download(parts[2],query.get('run',[''])[0],query.get('asset',[''])[0])
                self._studio_stream(target, download=True)
            else:
                self._json({"error": "경로를 찾을 수 없습니다."}, 404)
        except (ValueError, KeyError, OSError) as exc:
            self._json({"error": str(exc)}, 404)
        except RuntimeError as exc:
            self._json({'error':str(exc)},503)
        return True

    def _studio_stream(self, target, download=False):
        size = target.stat().st_size
        start, end, status = 0, size - 1, 200
        header = self.headers.get("Range")
        if header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", header)
            if not match or not any(match.groups()):
                self.send_error(416); return
            a, b = match.groups()
            if a:
                start, end = int(a), min(int(b), end) if b else end
            else:
                start = max(0, size - int(b))
            if start > end or start >= size:
                self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        if download:
            from urllib.parse import quote
            self.send_header('Content-Disposition', "attachment; filename*=UTF-8''"+quote(target.name))
        if status == 206: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with target.open("rb") as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(256 * 1024, remaining))
                    if not chunk: break
                    self.wfile.write(chunk); remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
