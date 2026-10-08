"""Optional CLIP model lifecycle and product-frame matching."""
from __future__ import annotations
from pathlib import Path
from PIL import Image
from ..config import Settings
from .catalog import PRODUCT_CONCEPTS

class OpenClipVerifier:
    """한 작업에서 모델/기준 임베딩을 한 번만 로드하는 선택적 의미 유사도 검증기."""
    def __init__(self, settings: Settings, reference_frames: list[Path]):
        self.settings = settings
        self.available = False
        self.error = ""
        self.product_evidence: list[dict] = []
        self.last_embedding = None
        self.subject_reference_indices: list[int] = []
        if not settings.source_use_openclip:
            return
        try:
            import torch
            import open_clip
            self.open_clip = open_clip
            self.torch = torch
            self.device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
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
        top = (best.mean() if self.subject_reference_indices else
               best.topk(min(3, best.numel())).values.mean()).item()
        return round(max(0.0, min(1.0, top)), 4)

    def focus_subject(self, products: list[dict]) -> None:
        """Compare against product frames, not a matching celebrity in the hook."""
        if not self.available:
            return
        subjects = [p['en'] for p in products if p.get('en') and
                    set(p.get('sources', [])) & {'caption', 'speech', 'screen_text'}]
        if not subjects:
            return
        prompts = [f'a close up product demonstration of {s}' for s in subjects]
        prompts += ['a celebrity man at an airport', 'a person sitting in an airplane',
                    'a portrait of a person talking', 'a landscape or building']
        tokenizer = self.open_clip.get_tokenizer(self.settings.source_openclip_model)
        with self.torch.no_grad():
            features = self.model.encode_text(tokenizer(prompts).to(self.device))
            features /= features.norm(dim=-1, keepdim=True)
            matrix = self.reference @ features.T
            subject = matrix[:, :len(subjects)].max(dim=1).values.tolist()
            background = matrix[:, len(subjects):].max(dim=1).values.tolist()
        from ..source_quality import subject_frame_indices
        indices = subject_frame_indices(subject, background)
        if indices:
            self.reference = self.reference[indices]
            self.subject_reference_indices = indices

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
