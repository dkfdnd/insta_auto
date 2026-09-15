"""릴스의 장면을 바탕으로 공개 웹에서 재료 영상 후보를 찾고 검증한다.

외부 서비스의 로그인/DRM/봇 차단을 우회하지 않는다. 다운로드한 후보의 사용 권리는
별도 확인이 필요하며, 출처와 탐색 근거를 manifest.json에 보존한다.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import threading
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, unquote, urlparse

import requests
from PIL import Image, ImageOps

from .config import Settings
from .storage import Storage
from .source_quality import (platform_of, round_robin_candidates, sha256_file,
                             relevance_reasons, reuse_reasons, select_valid_candidates)

Progress = Callable[[str, int], None]
VIDEO_HOSTS = ("tiktok.com", "douyin.com", "xiaohongshu.com", "youtube.com", "youtu.be", "bilibili.com",
               "vimeo.com", "lazada.", "manuals.plus", "made-in-china.com")
SOURCE_COOLDOWNS: dict[str, float] = {}
KO_EN_ZH = {
    "차량": ("car", "汽车"), "자동차": ("car", "汽车"), "차문": ("car door", "车门"),
    "차량용품": ("car accessories", "汽车用品"), "문쪽": ("door side", "车门侧"),
    "컵홀더": ("cup holder", "杯架"), "홀더": ("holder", "支架"), "음료": ("drink", "饮料"),
    "커피": ("coffee", "咖啡"), "수납": ("organizer", "收纳"), "쓰레기통": ("trash bin", "垃圾桶"),
    "주방": ("kitchen", "厨房"), "캠핑": ("camping", "露营"), "에어컨": ("air conditioner", "空调"),
    "소파": ("sofa", "沙发"), "조개": ("shellfish", "贝类"), "귀지": ("ear wax", "耳垢"),
}

# CLIP은 번역기가 아니라 영상 속 물체/사용 장면을 이 카탈로그에 매칭한다. 너무 넓은 단어보다
# 실제 숏폼 검색에 쓰이는 상품명 표현을 영어·중국어 쌍으로 관리한다.
PRODUCT_CONCEPTS = [
    ("car door cup holder organizer", "车门挂式杯架 汽车收纳"),
    ("car seat gap organizer", "汽车座椅缝隙收纳盒"),
    ("car interior cleaning tool", "汽车内饰清洁工具"),
    ("portable car trash bin", "车载便携垃圾桶"),
    ("kitchen storage organizer", "厨房收纳神器"),
    ("refrigerator storage container", "冰箱收纳盒"),
    ("sink cleaning brush", "水槽清洁刷"),
    ("vegetable slicer kitchen gadget", "多功能切菜器 厨房神器"),
    ("food storage container", "食品保鲜收纳盒"),
    ("bathroom cleaning tool", "浴室清洁神器"),
    ("toilet cleaning brush", "马桶清洁刷"),
    ("shower storage rack", "浴室置物架"),
    ("laundry folding organizer", "衣物折叠收纳"),
    ("closet space saving hanger", "衣柜省空间衣架"),
    ("home cleaning mop", "家用清洁拖把"),
    ("window cleaning tool", "玻璃窗清洁神器"),
    ("sofa and carpet cleaning tool", "沙发地毯清洁神器"),
    ("portable fan", "便携小风扇"),
    ("air conditioner accessory", "空调实用配件"),
    ("desk organizer", "桌面收纳神器"),
    ("phone holder stand", "手机支架"),
    ("charging cable organizer", "数据线收纳器"),
    ("beauty skin care tool", "美容护肤工具"),
    ("hair styling tool", "美发造型工具"),
    ("makeup organizer", "化妆品收纳盒"),
    ("ear cleaning tool", "可视采耳工具"),
    ("pet grooming tool", "宠物美容清洁工具"),
    ("pet hair remover", "宠物毛发清理器"),
    ("camping storage gear", "露营收纳装备"),
    ("portable outdoor light", "户外便携灯"),
    ("handheld repair tool", "家用维修工具"),
    ("shoe cleaning tool", "鞋子清洁神器"),
    ("travel organizer bag", "旅行收纳袋"),
    ("baby feeding product", "婴儿喂养用品"),
]


@dataclass
class Candidate:
    url: str
    provider: str
    original_url: str = ""
    title: str = ""
    uploader: str = ""
    query: str = ""
    match_kind: str = "keyword"
    rights: str = "unknown-check-before-reuse"
    downloaded_file: str = ""
    preview_file: str = ""
    hash_similarity: float | None = None
    semantic_similarity: float | None = None
    similarity: float | None = None
    match_quality: str = "unverified"
    source_quality: str = "unknown"
    text_overlay_score: float | None = None
    text_frame_ratio: float | None = None
    caption_frame_ratio: float | None = None
    watermark_frame_ratio: float | None = None
    source_score: float | None = None
    platform: str = "other"
    video_meta: dict | None = None
    file_sha256: str = ""
    frame_hashes: list[str] | None = None
    selection_reason: str = ""
    rejection_reasons: list[str] | None = None
    selected_for_zip: bool = False
    error: str = ""

    def __post_init__(self) -> None:
        self.original_url = self.original_url or self.url
        self.platform = platform_of(self.provider, self.url)


def _run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _safe_name(text: str, limit: int = 70) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", text).strip("._")[:limit]
    return value or "video"


def _post(settings: Settings, shortcode: str):
    store = Storage(settings.db_path)
    row = store.conn.execute("SELECT * FROM posts WHERE shortcode=?", (shortcode,)).fetchone()
    if not row:
        store.close()
        raise ValueError(f"게시물을 찾지 못했습니다: {shortcode}")
    post = Storage._row_to_post(row)
    store.close()
    return post


def _download_reference(settings: Settings, post, out: Path) -> Path:
    """저장된 Instagram 세션으로 공개 게시물의 기준 영상을 받는다."""
    from .collectors.web_graphql import WebGraphQLCollector

    if not post.media_id:
        raise RuntimeError("이 게시물에는 media_id가 없어 기준 영상을 가져올 수 없습니다.")
    collector = WebGraphQLCollector(settings)
    r = collector.s.get(
        f"https://www.instagram.com/api/v1/media/{post.media_id}/info/",
        headers=collector._api_headers(post.url), timeout=30,
    )
    r.raise_for_status()
    item = ((r.json() or {}).get("items") or [{}])[0]
    versions = item.get("video_versions") or []
    if not versions:
        raise RuntimeError("Instagram 응답에 다운로드 가능한 video_versions가 없습니다.")
    source = max(versions, key=lambda v: (v.get("width", 0) * v.get("height", 0), v.get("type", 0)))
    video = collector.s.get(source["url"], stream=True, timeout=60)
    video.raise_for_status()
    limit = settings.source_max_file_mb * 1024 * 1024
    size = 0
    with out.open("wb") as f:
        for chunk in video.iter_content(1024 * 256):
            size += len(chunk)
            if size > limit:
                raise RuntimeError("기준 영상이 설정된 최대 크기를 초과했습니다.")
            f.write(chunk)
    return out


def extract_frames(video: Path, frame_dir: Path, prefix: str = "frame", max_frames: int = 12) -> list[Path]:
    """균등 샘플과 장면 변화 프레임을 합친 뒤 중복 지문을 제거한다."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg/ffprobe가 필요합니다.")
    frame_dir.mkdir(parents=True, exist_ok=True)
    probe = _run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)])
    try:
        duration = max(1.0, float(probe.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError("영상 길이를 읽지 못했습니다.") from exc
    interval = max(0.7, duration / max(4, max_frames - 2))
    pattern = str(frame_dir / f"{prefix}_%03d.jpg")
    result = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video),
                   "-vf", f"fps=1/{interval:.3f},scale=480:-2", "-q:v", "3", pattern])
    if result.returncode:
        raise RuntimeError(f"프레임 추출 실패: {result.stderr[-300:]}")
    files = sorted(frame_dir.glob(f"{prefix}_*.jpg"))
    unique: list[Path] = []
    hashes: list[int] = []
    for path in files:
        h = dhash(path)
        if not hashes or min((h ^ old).bit_count() for old in hashes) >= 5:
            unique.append(path); hashes.append(h)
        else:
            path.unlink(missing_ok=True)
    return unique[:max_frames]


def dhash(path: Path) -> int:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("L")
        # 상하 자막/워터마크의 영향을 줄이고 실제 장면 중심부를 비교한다.
        w, h = image.size
        image = image.crop((0, int(h * .12), w, int(h * .84))).resize((17, 16), Image.Resampling.LANCZOS)
        px = list(image.get_flattened_data())
    bits = 0
    for y in range(16):
        for x in range(16):
            bits = (bits << 1) | (px[y * 17 + x] > px[y * 17 + x + 1])
    return bits


def compare_videos(reference_frames: list[Path], candidate: Path, work: Path) -> float:
    cframes = extract_frames(candidate, work, "candidate", max_frames=16)
    if not cframes or not reference_frames:
        return 0.0
    left = [dhash(p) for p in reference_frames]
    right = [dhash(p) for p in cframes]
    best = [1.0 - min((a ^ b).bit_count() for b in right) / 256 for a in left]
    # 한 장의 우연한 일치보다 여러 장면 일치를 보상한다.
    top = sorted(best, reverse=True)[:min(3, len(best))]
    return round(sum(top) / len(top), 4)


def probe_video(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"duration": None, "width": None, "height": None, "bytes": path.stat().st_size}
    result = _run([ffprobe, "-v", "error", "-show_entries",
                   "format=duration:stream=width,height", "-of", "json", str(path)], timeout=30)
    try:
        info = json.loads(result.stdout)
        stream = next((row for row in info.get("streams", []) if row.get("width") and row.get("height")), {})
        return {"duration": float(info.get("format", {}).get("duration") or 0),
                "width": stream.get("width"), "height": stream.get("height"),
                "bytes": path.stat().st_size}
    except (ValueError, json.JSONDecodeError):
        return {"duration": None, "width": None, "height": None, "bytes": path.stat().st_size}


class OpenClipVerifier:
    """한 작업에서 모델/기준 임베딩을 한 번만 로드하는 선택적 의미 유사도 검증기."""
    def __init__(self, settings: Settings, reference_frames: list[Path]):
        self.settings = settings
        self.available = False
        self.error = ""
        self.product_evidence: list[dict] = []
        self.last_embedding = None
        if not settings.source_use_openclip:
            return
        try:
            import torch
            import open_clip
            self.open_clip = open_clip
            self.torch = torch
            self.device = "mps" if torch.backends.mps.is_available() else "cpu"
            self.model, _, self.preprocess = open_clip.create_model_and_transforms(
                settings.source_openclip_model, pretrained=settings.source_openclip_pretrained,
                cache_dir=str(settings.source_model_dir), device=self.device,
            )
            self.model.eval()
            self.reference = self._encode(reference_frames)
            self.available = self.reference is not None
        except Exception as exc:  # noqa: BLE001
            self.error = f"OpenCLIP 비활성: {type(exc).__name__}: {str(exc)[:220]}"

    def _encode(self, paths: list[Path]):
        if not paths:
            return None
        tensors = []
        for path in paths:
            with Image.open(path) as image:
                tensors.append(self.preprocess(image.convert("RGB")))
        batch = self.torch.stack(tensors).to(self.device)
        with self.torch.no_grad():
            features = self.model.encode_image(batch)
            features /= features.norm(dim=-1, keepdim=True)
        return features

    def score(self, candidate_frames: list[Path]) -> float | None:
        self.last_embedding = None
        if not self.available:
            return None
        features = self._encode(candidate_frames)
        if features is None:
            return None
        self.last_embedding = features.mean(dim=0)
        self.last_embedding /= self.last_embedding.norm()
        matrix = self.reference @ features.T
        best = matrix.max(dim=1).values
        top = best.topk(min(3, best.numel())).values.mean().item()
        return round(max(0.0, min(1.0, top)), 4)

    def discover_product_queries(self, count: int = 2) -> list[str]:
        """기준 장면과 가까운 상품 개념을 골라 영어·중국어 검색어 쌍을 만든다."""
        if not self.available:
            return []
        prompts = [f"a short product demonstration video of {english}" for english, _ in PRODUCT_CONCEPTS]
        try:
            tokenizer = self.open_clip.get_tokenizer(self.settings.source_openclip_model)
        except AttributeError:
            tokenizer = self.open_clip.tokenize
        with self.torch.no_grad():
            tokens = tokenizer(prompts).to(self.device)
            features = self.model.encode_text(tokens)
            features /= features.norm(dim=-1, keepdim=True)
            # 제품이 잘 보이는 한두 장면을 살리되 우연한 한 프레임 매칭은 평균 점수로 보정한다.
            matrix = self.reference @ features.T
            scores = matrix.max(dim=0).values * .7 + matrix.mean(dim=0) * .3
            ranked = scores.topk(min(count + 1, scores.numel())).indices.tolist()
            values = scores.tolist()
        queries = []
        for rank, index in enumerate(ranked[:count]):
            score = float(values[index])
            next_score = float(values[ranked[rank + 1]]) if rank + 1 < len(ranked) else 0
            if score < .26 or score - next_score < .025:
                continue
            queries.extend(PRODUCT_CONCEPTS[index])
            self.product_evidence.append({"concept": PRODUCT_CONCEPTS[index][0],
                                          "score": round(score, 4), "margin": round(score - next_score, 4)})
        return queries


def _keywords(caption: str) -> list[str]:
    clean = re.sub(r"https?://\S+|[@#][\w.]+|[^0-9A-Za-z가-힣 ]+", " ", caption)
    stop = {"댓글", "남겨주세요", "정보", "진짜", "이건", "있어서", "있고", "하나씩", "있는", "너무", "사용", "제품"}
    words = [w for w in clean.split() if 2 <= len(w) <= 12 and w not in stop]
    scored = sorted(set(words), key=lambda w: (w in KO_EN_ZH, len(w)), reverse=True)
    return scored[:8]


def build_queries(caption: str) -> list[str]:
    words = _keywords(caption)
    concepts = [key for key in KO_EN_ZH if key in caption]
    mapped = [KO_EN_ZH[w] for w in concepts]
    ko = " ".join((concepts + words)[:6])
    en = " ".join(dict.fromkeys(x[0] for x in mapped[:4])) or " ".join(words[:4])
    zh = " ".join(dict.fromkeys(x[1] for x in mapped[:4])) or " ".join(words[:4])
    if any(x in caption for x in ("차량", "자동차", "차문")) and any(x in caption for x in ("컵", "홀더", "음료")):
        en = "car door hanging cup holder organizer"
        zh = "车门挂式杯架 汽车收纳"
    intent = []
    if "car door" in en:
        intent = ["car door hanging cup holder", "car door cup holder", "car door hanging trash can cup holder", "车门 挂式 杯架 垃圾桶"]
    return [q for q in dict.fromkeys((ko, *intent, en, zh)) if q.strip()]


def _clean_visual_terms(terms: list[str]) -> list[str]:
    generic = {"text in image", "person", "people", "human", "car", "vehicle", "video", "image", "photo"}
    return [term.strip() for term in dict.fromkeys(terms)
            if term.strip() and term.strip().lower() not in generic and len(term.strip()) >= 3]


def _transcript_evidence(settings: Settings, shortcode: str) -> dict[str, str]:
    paths = sorted(settings.transcript_dir.glob(f"{shortcode}-*/transcript.json"), reverse=True)
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {key: " ".join(row.get("text", "") for row in data.get(key, []))
                    for key in ("speech", "screen_text")}
        except (OSError, json.JSONDecodeError):
            continue
    return {"speech": "", "screen_text": ""}


def build_grounded_queries(caption: str, visual_queries: list[str], vision_terms: list[str],
                           transcript: dict[str, str]) -> list[dict]:
    """캡션·시각·화면 글자·실제 음성의 생성 근거를 검색어별로 남긴다."""
    sources = {"caption": caption, "vision": " ".join(_clean_visual_terms(vision_terms)),
               "screen_text": transcript.get("screen_text", ""), "speech": transcript.get("speech", "")}
    grounded = []
    roles = {"차문": "place", "주방": "place", "캠핑": "place", "소파": "place",
             "컵홀더": "product", "홀더": "shape", "수납": "behavior", "청소": "behavior"}
    for word, (english, chinese) in KO_EN_ZH.items():
        if english in {"car", "drink", "coffee", "sofa", "shellfish"}:
            continue
        evidence = [name for name, body in sources.items() if word in body]
        if len(evidence) >= 2:
            for query in (english, chinese):
                grounded.append({"query": query, "sources": evidence, "confidence": "high",
                                 "role": roles.get(word, "product")})
    for query in visual_queries:
        evidence = ["openclip"]
        if any(word in caption.lower() for word in query.lower().split() if len(word) >= 4):
            evidence.append("caption")
        grounded.append({"query": query, "sources": evidence,
                         "confidence": "high" if len(evidence) >= 2 else "medium", "role": "product"})
    if not grounded:
        grounded = [{"query": query, "sources": ["caption"], "confidence": "low", "role": "fallback"}
                    for query in build_queries(caption)]
    deduped = {}
    for item in grounded:
        deduped.setdefault(item["query"], item)
    return list(deduped.values())[:16]


def _yt_cookie_args(cookie_file: Path | None) -> list[str]:
    return ["--cookies", str(cookie_file)] if cookie_file and cookie_file.is_file() else []


def search_youtube(queries: list[str], limit: int, cookie_file: Path | None = None) -> list[Candidate]:
    """yt-dlp의 공개 YouTube 검색 추출기로 Shorts/제품 시연 후보를 찾는다."""
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp or limit <= 0:
        return []
    out: list[Candidate] = []
    # 영어/중국어 검색이 글로벌 제품 소스에 가장 잘 맞는다.
    english_queries = [query for query in queries if re.search(r"[A-Za-z]", query)
                       and not re.search(r"[\u3400-\u9fff]", query)]
    for query in (english_queries[:3] or queries[:1]):
        count = min(6, max(2, limit - len(out)))
        suffix = " shorts" if not re.search(r"[\u3400-\u9fff]", query) else ""
        result = _run([ytdlp, *_yt_cookie_args(cookie_file), "--flat-playlist", "--dump-single-json",
                       "--no-warnings", f"ytsearch{count}:{query}{suffix}"], timeout=90)
        try:
            entries = json.loads(result.stdout).get("entries") or []
        except (json.JSONDecodeError, AttributeError):
            entries = []
        for item in entries:
            url = item.get("webpage_url") or item.get("url") or ""
            if url and not url.startswith("http") and item.get("id"):
                url = f"https://www.youtube.com/watch?v={item['id']}"
            if url:
                out.append(Candidate(url=url, provider="youtube", title=item.get("title") or "", query=query))
        if len(out) >= limit:
            break
    return _dedupe(out)[:limit]


def _unwrap_ddg(url: str) -> str:
    if "duckduckgo.com/l/" in url:
        return unquote(parse_qs(urlparse(url).query).get("uddg", [url])[0])
    return url


def search_web(queries: list[str], limit: int) -> list[Candidate]:
    out: list[Candidate] = []
    headers = {"User-Agent": "Mozilla/5.0 (compatible; hotpost-source-finder/1.0)"}
    for query in queries:
        scoped = f'{query} (site:tiktok.com OR site:douyin.com OR site:xiaohongshu.com OR site:youtube.com/shorts OR site:bilibili.com)'
        try:
            r = requests.get("https://html.duckduckgo.com/html/", params={"q": scoped}, headers=headers, timeout=20)
            r.raise_for_status()
        except requests.RequestException:
            continue
        for href, title in re.findall(r'class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
            url = _unwrap_ddg(html.unescape(href))
            if not any(host in urlparse(url).netloc.lower() for host in VIDEO_HOSTS):
                continue
            out.append(Candidate(url=url, provider=urlparse(url).netloc, title=re.sub("<.*?>", "", html.unescape(title)), query=query))
            if len(out) >= limit:
                return _dedupe(out)
    return _dedupe(out)


def search_bing(queries: list[str], limit: int) -> list[Candidate]:
    """키 없는 공개 검색 폴백. 영상 플랫폼과 상품 시연 페이지를 함께 찾는다."""
    out: list[Candidate] = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36"}
    for query in queries:
        try:
            r = requests.get("https://www.bing.com/search", params={"q": f'"{query}" video'}, headers=headers, timeout=20)
            r.raise_for_status()
        except requests.RequestException:
            continue
        blocks = re.findall(r'<li class="b_algo".*?</li>', r.text, re.S)
        for block in blocks:
            match = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not match:
                continue
            url, title = html.unescape(match.group(1)), re.sub("<.*?>", "", html.unescape(match.group(2)))
            if any(host in urlparse(url).netloc.lower() for host in VIDEO_HOSTS):
                out.append(Candidate(url=url, provider=urlparse(url).netloc, title=title, query=query))
                if len(out) >= limit:
                    return _dedupe(out)
    return _dedupe(out)


def search_google_vision(settings: Settings, frames: list[Path], limit: int) -> tuple[list[Candidate], list[str]]:
    key = settings.source_google_vision_api_key or os.environ.get("GOOGLE_CLOUD_VISION_API_KEY", "")
    if not key:
        return [], []
    out: list[Candidate] = []
    terms: list[str] = []
    for frame in frames[:6]:
        payload = {"requests": [{"image": {"content": base64.b64encode(frame.read_bytes()).decode()},
                                  "features": [{"type": "WEB_DETECTION", "maxResults": 15},
                                               {"type": "LABEL_DETECTION", "maxResults": 10}]}]}
        try:
            r = requests.post(f"https://vision.googleapis.com/v1/images:annotate?key={key}", json=payload, timeout=30)
            r.raise_for_status()
            response = (r.json().get("responses") or [{}])[0]
            web = response.get("webDetection") or {}
        except requests.RequestException:
            continue
        terms.extend(label.get("label", "") for label in web.get("bestGuessLabels", []))
        terms.extend(entity.get("description", "") for entity in web.get("webEntities", [])
                     if float(entity.get("score") or 0) >= .35)
        terms.extend(label.get("description", "") for label in response.get("labelAnnotations", [])
                     if float(label.get("score") or 0) >= .70)
        for page in web.get("pagesWithMatchingImages", []):
            url = page.get("url", "")
            if any(host in urlparse(url).netloc.lower() for host in VIDEO_HOSTS):
                out.append(Candidate(url=url, provider="google-vision", title=page.get("pageTitle", ""),
                                     query=frame.name, match_kind="visual-match"))
                if len(out) >= limit:
                    return _dedupe(out), [x for x in dict.fromkeys(terms) if x][:12]
    return _dedupe(out), [x for x in dict.fromkeys(terms) if x][:12]


def search_pexels(settings: Settings, queries: list[str], limit: int) -> list[Candidate]:
    key = settings.source_pexels_api_key or os.environ.get("PEXELS_API_KEY", "")
    if not key:
        return []
    out: list[Candidate] = []
    for query in queries[1:2] or queries[:1]:
        try:
            r = requests.get("https://api.pexels.com/v1/videos/search", params={"query": query, "orientation": "portrait", "per_page": min(limit, 10)},
                             headers={"Authorization": key}, timeout=30)
            r.raise_for_status()
        except requests.RequestException:
            continue
        for item in r.json().get("videos", []):
            files = item.get("video_files") or []
            if not files:
                continue
            f = max(files, key=lambda x: (x.get("width") or 0) * (x.get("height") or 0))
            out.append(Candidate(url=f.get("link", ""), provider="pexels", title=f"Pexels video {item.get('id')}", query=query,
                                 match_kind="stock-b-roll", rights="pexels-license"))
    return _dedupe(out)


def search_local_cache(settings: Settings, shortcode: str, limit: int) -> list[Candidate]:
    """같은 릴스에서 이미 검증·다운로드한 후보를 재사용한다."""
    out: list[Candidate] = []
    manifests = sorted(settings.source_dir.glob(f"{shortcode}-*/manifest.json"), reverse=True)
    for path in manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for item in data.get("candidates", []):
            if not item.get("downloaded_file") or not item.get("url"):
                continue
            out.append(Candidate(url=item["url"], provider=item.get("provider", "cache"), title=item.get("title", ""),
                                 uploader=item.get("uploader", ""),
                                 query=item.get("query", ""), match_kind="cached-candidate", rights=item.get("rights", "unknown-check-before-reuse")))
            if len(_dedupe(out)) >= limit:
                return _dedupe(out)[:limit]
    return _dedupe(out)[:limit]


def _dedupe(items: list[Candidate]) -> list[Candidate]:
    seen = set(); out = []
    for item in items:
        parsed = urlparse(item.url)
        if "youtube.com" in parsed.netloc and parsed.path == "/watch":
            normalized = f"https://youtube.com/watch?v={parse_qs(parsed.query).get('v', [''])[0]}"
        elif "youtu.be" in parsed.netloc:
            normalized = f"https://youtu.be/{parsed.path.strip('/')}"
        else:
            normalized = item.url.split("?")[0].rstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized); out.append(item)
    return out


def download_candidate(candidate: Candidate, out_dir: Path, index: int, max_mb: int,
                       cookie_file: Path | None = None) -> Path | None:
    if SOURCE_COOLDOWNS.get(candidate.platform, 0) > time.time():
        candidate.error = "429 쿨다운 중인 플랫폼"
        return None
    stem = f"{index:02d}_{_safe_name(candidate.provider)}"
    parsed = urlparse(candidate.url)
    video_id = parse_qs(parsed.query).get("v", [""])[0] if "youtube.com" in parsed.netloc else parsed.path.strip("/").split("/")[-1]
    if video_id:
        cache_root = out_dir.parent.parent
        cached = next((p for p in cache_root.glob(f"*/videos/*_{video_id}.*") if p.parent != out_dir and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}), None)
        if cached:
            target = out_dir / f"{stem}_{video_id}{cached.suffix.lower()}"
            shutil.copy2(cached, target)
            return target
    if candidate.provider == "pexels":
        target = out_dir / f"{stem}.mp4"
        for attempt in range(3):
            try:
                with requests.get(candidate.url, stream=True, timeout=60) as r:
                    if r.status_code == 429:
                        SOURCE_COOLDOWNS[candidate.platform] = time.time() + 60
                        candidate.error = "429 제한 · 60초 쿨다운"
                        return None
                    r.raise_for_status(); size = 0
                    with target.open("wb") as f:
                        for chunk in r.iter_content(1024 * 256):
                            size += len(chunk)
                            if size > max_mb * 1024 * 1024:
                                raise RuntimeError("파일 크기 제한 초과")
                            f.write(chunk)
                return target
            except Exception as exc:  # noqa: BLE001
                target.unlink(missing_ok=True); candidate.error = str(exc)[:240]
                if attempt < 2 and isinstance(exc, requests.RequestException):
                    time.sleep(2 ** attempt)
                    continue
                return None
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        candidate.error = "yt-dlp 실행 파일이 없습니다."
        return None
    template = str(out_dir / f"{stem}_%(id)s.%(ext)s")
    command = [ytdlp, *_yt_cookie_args(cookie_file), "--no-playlist", "--no-progress",
               "--restrict-filenames", "--write-info-json", "--max-filesize", f"{max_mb}M",
               "--format", "bv*+ba/b", "--merge-output-format", "mp4", "-o", template,
               "--", candidate.url]
    for attempt in range(3):
        try:
            result = _run(command, timeout=240)
        except subprocess.TimeoutExpired:
            candidate.error = "다운로드 제한 시간(240초) 초과"
            return None
        diagnostic = (result.stderr or result.stdout).lower()
        if "429" in diagnostic or "too many requests" in diagnostic:
            SOURCE_COOLDOWNS[candidate.platform] = time.time() + 60
            candidate.error = "429 제한 · 60초 쿨다운"
            return None
        if result.returncode == 0 or any(word in diagnostic for word in ("login", "captcha", "drm", "private")):
            break
        if attempt < 2:
            time.sleep(2 ** attempt)
    info_file = next(iter(out_dir.glob(f"{stem}_*.info.json")), None)
    if info_file:
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
            candidate.title = info.get("title") or candidate.title
            candidate.uploader = info.get("uploader") or info.get("channel") or ""
            candidate.url = info.get("webpage_url") or candidate.url
        except (OSError, json.JSONDecodeError):
            pass
    files = sorted(out_dir.glob(f"{stem}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    video = next((p for p in files if p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}), None)
    if not video:
        candidate.error = (result.stderr or result.stdout)[-350:].strip()
    return video


def create_contact_sheet(frames: list[Path], out: Path) -> None:
    if not frames:
        return
    thumbs = []
    for p in frames:
        with Image.open(p) as im:
            x = ImageOps.fit(im.convert("RGB"), (180, 320), method=Image.Resampling.LANCZOS)
            thumbs.append(x.copy())
    cols = min(4, len(thumbs)); rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 180, rows * 320), "white")
    for i, im in enumerate(thumbs): sheet.paste(im, ((i % cols) * 180, (i // cols) * 320))
    sheet.save(out, quality=88)


def find_sources(settings: Settings, shortcode: str, progress: Progress | None = None) -> dict:
    progress = progress or (lambda _m, _p: None)
    post = _post(settings, shortcode)
    if not post.is_video:
        raise ValueError("소스 영상 탐색은 릴스/동영상만 지원합니다.")
    job_id = f"{shortcode}-{int(time.time())}"
    root = settings.source_dir / job_id
    frames_dir = root / "reference_frames"; candidates_dir = root / "videos"; compare_dir = root / "compare"
    candidates_dir.mkdir(parents=True); compare_dir.mkdir(parents=True)
    progress("기준 릴스를 가져오는 중", 8)
    reference = _download_reference(settings, post, root / "reference.mp4")
    progress("장면을 추출하는 중", 20)
    frames = extract_frames(reference, frames_dir)
    create_contact_sheet(frames, root / "reference_contact_sheet.jpg")
    progress("영상 속 제품을 영어·중국어 키워드로 분석하는 중", 24)
    verifier = OpenClipVerifier(settings, frames)
    verification_notes = [verifier.error] if verifier.error else []
    visual_queries = verifier.discover_product_queries()
    vision_candidates, vision_terms = search_google_vision(settings, frames, settings.source_max_candidates)
    query_details = build_grounded_queries(post.caption, visual_queries, vision_terms,
                                           _transcript_evidence(settings, shortcode))
    queries = [item["query"] for item in query_details]
    progress("영어·중국어로 TikTok·Douyin·Xiaohongshu 검색 중", 32)
    browser_result = {"candidates": [], "terms": [], "notes": []}
    if settings.source_browser_search:
        from .browser_search import browser_search
        browser_result = browser_search(settings, frames, queries, settings.source_max_candidates, root / "browser_debug")
    # Yandex가 반환한 일반 장면·외국어 단어가 제품 키워드를 밀어내지 않도록 뒤에 둔다.
    browser_terms = _clean_visual_terms(browser_result["terms"])
    queries = list(dict.fromkeys([*queries, *browser_terms]))
    candidates = [Candidate(**item) for item in browser_result["candidates"]] + vision_candidates
    progress("공개 웹 검색 결과를 합치는 중", 42)
    per_platform = max(4, settings.source_max_candidates // 5)
    candidates += search_local_cache(settings, shortcode, per_platform)
    candidates += search_web(queries, per_platform)
    candidates += search_bing(queries, per_platform)
    candidates += search_youtube(queries, per_platform,
                                 settings.source_browser_cookie_file)
    candidates += search_pexels(settings, queries, per_platform)
    candidates = round_robin_candidates(_dedupe(candidates), settings.source_max_candidates)
    from .text_overlay import TextOverlayDetector
    overlay_detector = TextOverlayDetector(settings)
    if overlay_detector.note:
        verification_notes.append(overlay_detector.note)
    progress(f"후보 {len(candidates)}개를 확인하는 중", 50)
    probed = 0
    embeddings = {}
    for i, candidate in enumerate(candidates, 1):
        if probed >= max(settings.source_max_downloads, settings.source_max_probe_downloads):
            break
        path = download_candidate(candidate, candidates_dir, i, settings.source_max_file_mb,
                                  settings.source_browser_cookie_file)
        if path:
            probed += 1
            candidate.downloaded_file = str(path.relative_to(root))
            candidate.video_meta = probe_video(path)
            candidate.file_sha256 = sha256_file(path)
            try:
                candidate.hash_similarity = compare_videos(frames, path, compare_dir / f"{i:02d}")
                candidate_frames = sorted((compare_dir / f"{i:02d}").glob("candidate_*.jpg"))
                candidate.semantic_similarity = verifier.score(candidate_frames)
                if verifier.last_embedding is not None:
                    embeddings[id(candidate)] = verifier.last_embedding.clone()
                candidate.frame_hashes = [f"{dhash(frame):064x}" for frame in candidate_frames]
                candidate.similarity = round(
                    candidate.hash_similarity if candidate.semantic_similarity is None else
                    candidate.hash_similarity * .55 + candidate.semantic_similarity * .45, 4,
                )
                candidate.match_quality = ("same-scene-likely" if candidate.similarity >= .82 else
                                           "close-match" if candidate.similarity >= .72 else "topic-related")
                overlay = overlay_detector.analyze(candidate_frames)
                for key, value in overlay.items():
                    if hasattr(candidate, key):
                        setattr(candidate, key, value)
                clean_score = {"clean-source": 1.0, "light-overlay": .62,
                               "edited-with-text": .2, "unknown": .45}[candidate.source_quality]
                semantic = candidate.semantic_similarity if candidate.semantic_similarity is not None else candidate.hash_similarity
                candidate.source_score = round(clean_score * .55 + (semantic or 0) * .30
                                               + (candidate.hash_similarity or 0) * .15
                                               - (.08 if (candidate.video_meta.get("width") or 0) > (candidate.video_meta.get("height") or 0) else 0)
                                               + (.03 if candidate.rights == "pexels-license" else 0), 4)
                preview = root / "previews" / f"{i:02d}.jpg"
                preview.parent.mkdir(exist_ok=True)
                create_contact_sheet(sorted((compare_dir / f"{i:02d}").glob("candidate_*.jpg"))[:8], preview)
                candidate.preview_file = str(preview.relative_to(root))
                candidate.rejection_reasons = [*relevance_reasons(candidate, candidate.video_meta),
                                               *reuse_reasons(candidate)]
            except Exception as exc:  # noqa: BLE001
                candidate.error = f"유사도 계산 실패: {exc}"
                candidate.rejection_reasons = ["verification_failed"]
        else:
            candidate.rejection_reasons = ["download_failed"]
        progress(f"후보 다운로드/검증 {i}/{len(candidates)}", min(88, 50 + int(i / max(1, len(candidates)) * 38)))
    candidates.sort(key=lambda c: (c.downloaded_file != "", c.source_score or 0, c.similarity or 0), reverse=True)
    selected = select_valid_candidates(candidates, settings.source_max_downloads, embeddings)
    downloaded = len(selected)
    quality_counts = {key: sum(c.selected_for_zip and c.source_quality == key for c in candidates)
                      for key in ("clean-source", "light-overlay", "edited-with-text", "unknown")}
    manifest = {
        "job_id": job_id, "created_at": int(time.time()), "shortcode": shortcode, "reference_url": post.url,
        "caption": post.caption, "queries": queries, "query_details": query_details,
        "visual_product_queries": visual_queries, "openclip_product_evidence": verifier.product_evidence,
        "google_vision_terms": vision_terms,
        "reference_frames": [str(p.relative_to(root)) for p in frames],
        "browser_notes": browser_result["notes"], "verification_notes": verification_notes,
        "candidates": [asdict(c) for c in candidates], "downloaded": downloaded,
        "probed_downloads": probed,
        "quality_counts": quality_counts,
        "rights_notice": "각 파일의 저작권과 상업적 이용 허가를 원 출처에서 확인한 뒤 사용하세요. Pexels 항목만 Pexels 라이선스로 표시됩니다.",
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # 기준 릴스는 분석용일 뿐 소스 ZIP에는 넣지 않는다.
    zip_path = root / f"sources_{shortcode}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(root / "manifest.json", "manifest.json")
        z.write(root / "reference_contact_sheet.jpg", "reference_contact_sheet.jpg")
        for c in candidates:
            if c.selected_for_zip:
                folder = {"clean-source": "clean_sources", "light-overlay": "review_needed",
                          "edited-with-text": "edited_references", "unknown": "unclassified"}[c.source_quality]
                z.write(root / c.downloaded_file, f"{folder}/{Path(c.downloaded_file).name}")
            if c.selected_for_zip and c.preview_file:
                z.write(root / c.preview_file, c.preview_file)
    progress("완료", 100)
    manifest["zip_path"] = str(zip_path)
    return manifest


class SourceJobManager:
    def __init__(self, settings: Settings, job_queue=None):
        from .job_queue import JobQueue
        self.settings = settings
        self.queue = job_queue or JobQueue(settings)
        self.queue.register("source", lambda shortcode, progress: find_sources(settings, shortcode, progress))

    def start(self, shortcode: str) -> dict:
        return self.queue.start("source", shortcode)

    def get(self, job_id: str) -> dict | None:
        return self.queue.get(job_id)
