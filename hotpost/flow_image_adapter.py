"""Durable Google Flow handoff, isolated from editorial and editing logic.

There is intentionally no guessed private API or session-token harvesting.
A future supported browser/API transport can consume the same request.json
and submit an image through accept_image(). Pending is never called success.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

from .thumbnail_planner import flow_prompt, validate_caption


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _image(path: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(path) as image:
        width, height = image.size
        if image.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Unsupported image format")
        image.verify()
    return width, height


class GoogleFlowImageAdapter:
    provider = "google_flow"

    def __init__(self, data_root: Path):
        self.data_root = data_root.resolve()

    def _local(self, path: Path, *, exists=True) -> Path:
        path = path.resolve(strict=exists)
        if not path.is_relative_to(self.data_root):
            raise ValueError("Flow job assets must stay under data_dir")
        return path

    def prepare(self, job_dir: Path, plan: dict, references: list[Path]) -> dict:
        job_dir = self._local(job_dir, exists=False)
        if not references or len(references) > 5:
            raise ValueError("Provide 1–5 authorized product reference images")
        refs = []
        for path in references:
            path = self._local(path)
            _image(path)
            refs.append({"path": str(path), "sha256": _hash(path)})
        validate_caption(plan["selected"]["text"])
        request = {"schema_version": "1.0", "provider": self.provider,
                   "status": "awaiting_image", "prompt": flow_prompt(plan),
                   "plan": plan, "references": refs,
                   "instructions": "Generate in Google Flow using the references; download and review product identity and copy before accept."}
        job_dir.mkdir(parents=True, exist_ok=False)
        (job_dir / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        (job_dir / "prompt.txt").write_text(request["prompt"], encoding="utf-8")
        return request

    def accept_image(self, job_dir: Path, image: Path, *, flow_url: str,
                     reviewed: bool = False) -> dict:
        job_dir, image = self._local(job_dir), self._local(image)
        request_path = job_dir / "request.json"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request.get("provider") != self.provider or request.get("status") != "awaiting_image":
            raise ValueError("Not a pending Google Flow image request")
        if reviewed is not True:
            raise ValueError("Review product identity, caption truth and legibility before accepting")
        url = urlparse(flow_url)
        if url.scheme != "https" or url.hostname not in {"labs.google", "flow.google", "flow.google.com"}:
            raise ValueError("flow_url must identify the actual Google Flow project/asset")
        for ref in request["references"]:
            if _hash(self._local(Path(ref["path"]))) != ref["sha256"]:
                raise ValueError("Reference changed; prepare a new job")
        width, height = _image(image)
        if width < 576 or height < 1024 or abs(width / height - 9 / 16) > .02:
            raise ValueError("Flow image must be 9:16, at least 576x1024")
        result_path = job_dir / "result.json"
        target = job_dir / ("cover" + image.suffix.lower())
        if result_path.exists() or target.exists():
            raise FileExistsError("Flow output already exists; create a new job for revisions")
        shutil.copy2(image, target)
        result = {"status": "completed", "provider": self.provider,
                  "request_sha256": _hash(request_path), "image_sha256": _hash(target),
                  "flow_url": flow_url, "image_path": str(target), "reviewed": True,
                  "text": request["plan"]["selected"]["text"]}
        placement = request["plan"].get("image_brief", {}).get("caption_placement")
        if placement is not None:
            result["placement"] = placement
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def editing_thumbnail(self, job_dir: Path) -> dict:
        job_dir = self._local(job_dir)
        result_path = job_dir / "result.json"
        if not result_path.is_file():
            raise ValueError("thumbnail_image_pending: complete the Google Flow handoff first")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed" or result.get("reviewed") is not True:
            raise ValueError("thumbnail is not reviewed/completed")
        if _hash(job_dir / "request.json") != result["request_sha256"]:
            raise ValueError("Thumbnail request changed after review")
        if _hash(self._local(Path(result["image_path"]))) != result["image_sha256"]:
            raise ValueError("Thumbnail image changed after review")
        return {key: result[key] for key in ("provider", "image_path", "text", "reviewed", "placement") if key in result}
