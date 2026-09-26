"""후보 프레임의 자막·워터마크를 찾아 재가공 영상과 깨끗한 소스를 구분한다."""
from __future__ import annotations

import re
import shutil
import statistics
import subprocess
from pathlib import Path

from PIL import Image

from .config import Settings


def _sample(paths: list[Path], count: int = 8) -> list[Path]:
    if len(paths) <= count:
        return paths
    return [paths[round(i * (len(paths) - 1) / (count - 1))] for i in range(count)]


def classify_overlay(text_ratio: float, caption_ratio: float, watermark_ratio: float,
                     median_coverage: float) -> tuple[str, float]:
    """OCR 지표를 사람이 쓰기 쉬운 소스 등급과 0~1 오버레이 점수로 변환한다."""
    score = min(1.0, caption_ratio * .55 + text_ratio * .20 + watermark_ratio * .15
                + min(1.0, median_coverage / .03) * .10)
    if caption_ratio >= .38 or score >= .55 or (text_ratio >= .75 and median_coverage >= .012 and watermark_ratio < .5):
        quality = "edited-with-text"
    elif watermark_ratio >= .30 or text_ratio >= .35 or score >= .25:
        quality = "light-overlay"
    else:
        quality = "clean-source"
    return quality, round(score, 4)


class TextOverlayDetector:
    def __init__(self, settings: Settings):
        self.enabled = settings.source_detect_text_overlays
        self.tesseract = shutil.which("tesseract") if self.enabled else None
        self.tessdata = settings.source_tessdata_dir
        self.languages = self._languages()
        self.note = ""
        self.reader = None
        if self.enabled and not self.tesseract:
            self.note = "Tesseract가 없어 자막·워터마크 분류를 건너뜀"
        elif self.enabled and not self.languages:
            self.note = "OCR 언어 데이터가 없어 자막·워터마크 분류를 건너뜀"
        if self.enabled and (not self.tesseract or not self.languages):
            try:
                import easyocr
                import torch
                self.reader = easyocr.Reader(['ko', 'en'], gpu=torch.cuda.is_available(),
                                            model_storage_directory=str(settings.source_model_dir / 'easyocr'),
                                            download_enabled=False, verbose=False)
                self.languages = ['ko', 'en']
                self.note = '저장된 EasyOCR 한국어·영어 모델 사용. 다른 언어의 텍스트 검출은 불완전할 수 있습니다.'
            except Exception:
                pass

    def reference_text(self, frames: list[Path]) -> str:
        if not self.reader and (not self.tesseract or not self.languages):
            return ''
        texts = []
        for frame in _sample(frames, 4):
            row = self._frame(frame)
            if row and row.get('text'):
                texts.append(row['text'])
        return ' '.join(dict.fromkeys(texts))[:4000]

    def _languages(self) -> list[str]:
        if not self.tesseract:
            return []
        local = [lang for lang in ("eng", "kor", "chi_sim") if (self.tessdata / f"{lang}.traineddata").is_file()]
        if local:
            return local
        try:
            result = subprocess.run([self.tesseract, "--list-langs"], capture_output=True, text=True,
                                    timeout=10, check=False)
            available = set(result.stdout.splitlines()[1:])
            return [lang for lang in ("eng", "kor", "chi_sim") if lang in available]
        except Exception:  # noqa: BLE001
            return []

    def analyze(self, frames: list[Path]) -> dict:
        if (not self.reader and (not self.tesseract or not self.languages)) or not frames:
            return {"source_quality": "unknown", "text_overlay_score": None, "text_frame_ratio": None,
                    "caption_frame_ratio": None, "watermark_frame_ratio": None, "ocr_languages": []}
        metrics = [self._frame(path) for path in _sample(frames)]
        valid = [item for item in metrics if item is not None]
        if not valid:
            return {"source_quality": "unknown", "text_overlay_score": None, "text_frame_ratio": None,
                    "caption_frame_ratio": None, "watermark_frame_ratio": None,
                    "ocr_languages": self.languages}
        n = len(valid)
        text_ratio = sum(item["has_text"] for item in valid) / n
        caption_ratio = sum(item["has_caption"] for item in valid) / n
        watermark_ratio = sum(item["has_watermark"] for item in valid) / n
        coverage = statistics.median(item["coverage"] for item in valid)
        quality, score = classify_overlay(text_ratio, caption_ratio, watermark_ratio, coverage)
        unreadable_ratio = sum(item.get('unreadable_text', False) for item in valid) / n
        if quality == 'clean-source' and unreadable_ratio >= .25:
            quality = 'unknown'
        return {"source_quality": quality, "text_overlay_score": score,
                "text_frame_ratio": round(text_ratio, 4), "caption_frame_ratio": round(caption_ratio, 4),
                "watermark_frame_ratio": round(watermark_ratio, 4),
                "ocr_languages": self.languages, 'ocr_unreadable_frame_ratio': round(unreadable_ratio, 4)}

    def _frame(self, path: Path) -> dict | None:
        if self.reader is not None:
            try:
                raw_lines = []
                # OpenCV의 Windows 문자열 경로 처리는 한글 경로에서 실패할 수 있다.
                for i, (box, text, confidence) in enumerate(self.reader.readtext(path.read_bytes(), detail=1)):
                    left = min(p[0] for p in box); top = min(p[1] for p in box)
                    width = max(p[0] for p in box) - left; height = max(p[1] for p in box) - top
                    raw_lines.append('\t'.join(map(str, [5, 1, i, 1, 1, 1, left, top, width, height, confidence * 100, text])))
            except Exception:
                return None
        else:
            command = [self.tesseract, str(path), 'stdout']
            if all((self.tessdata / f'{lang}.traineddata').is_file() for lang in self.languages):
                command += ['--tessdata-dir', str(self.tessdata)]
            command += ['-l', '+'.join(self.languages), '--psm', '11', 'tsv']
            try:
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=25, check=False)
            except (OSError, subprocess.TimeoutExpired):
                return None
            if result.returncode:
                return None
            raw_lines = result.stdout.splitlines()[1:]
        with Image.open(path) as image:
            width, height = image.size
        groups: dict[tuple[str, str, str], list[tuple[int, int, int, int, str]]] = {}
        unreadable_text = False
        for raw in raw_lines:
            cols = raw.split("\t", 11)
            if len(cols) < 12:
                continue
            try:
                left, top, box_w, box_h, confidence = map(float, (cols[6], cols[7], cols[8], cols[9], cols[10]))
            except ValueError:
                continue
            text = cols[11].strip()
            if confidence < 35 and box_w / width >= .08 and box_h / height >= .01:
                unreadable_text = True
            if confidence < 35 or not re.search(r"[0-9A-Za-z가-힣\u3400-\u9fff]", text):
                continue
            groups.setdefault((cols[2], cols[3], cols[4]), []).append(
                (int(left), int(top), int(box_w), int(box_h), text))
        lines = []
        handles = []
        for words in groups.values():
            chars = sum(len(re.sub(r"\W", "", word[4], flags=re.UNICODE)) for word in words)
            if chars < 2:
                continue
            left = min(word[0] for word in words); top = min(word[1] for word in words)
            right = max(word[0] + word[2] for word in words); bottom = max(word[1] + word[3] for word in words)
            line = (left, top, right, bottom, chars)
            lines.append(line)
            if any(re.search(r'@[\w.]{3,}', word[4]) for word in words):
                handles.append(line)
        area = max(1, width * height)
        coverage = min(1.0, sum((right - left) * (bottom - top) for left, top, right, bottom, _ in lines) / area)
        captions = [line for line in lines if line not in handles and .52 <= ((line[1] + line[3]) / 2 / height) <= .94
                    and (line[2] - line[0]) / width >= .08]
        watermarks = [line for line in lines if line in handles or ((line[0] + line[2]) / 2 / width < .22
                      or (line[0] + line[2]) / 2 / width > .78 or (line[1] + line[3]) / 2 / height < .18
                      or (line[1] + line[3]) / 2 / height > .84)]
        return {"has_text": bool(lines), "has_caption": bool(captions),
                "has_watermark": bool(watermarks), "coverage": coverage,
                'unreadable_text': unreadable_text,
                "text": ' '.join(word[4] for words in groups.values() for word in words)}
