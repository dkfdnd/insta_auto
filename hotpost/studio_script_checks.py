"""Refresh local script diagnostics over HTTP without rewriting stored text."""
import hashlib

from .studio_adapter import StudioAdapter


class ReviewUnavailable(ValueError):
    def __init__(self, message, candidates):
        super().__init__(message)
        self.candidates = candidates


def refresh_local_reviews(settings, reference, valid):
    adapter = StudioAdapter(settings)
    reference_hash = hashlib.sha256(reference.encode()).hexdigest()
    refreshed = []
    for offset, (index, item) in enumerate(valid):
        try:
            text = item['text']
            review = adapter.review(text, reference, evidence_mode='benchmark')
            script_hash = hashlib.sha256(text.encode()).hexdigest()
            if not isinstance(review, dict) or review.get('text') != text:
                raise ValueError('현재 규칙 검사에서 원래 대본이 변경되어 검사 결과를 사용하지 않았습니다.')
            for key in ('integrity_review', 'rewrite_review', 'quality_summary'):
                record = review.get(key, {})
                if (not isinstance(record, dict) or record.get('script_sha256') != script_hash
                        or record.get('reference_sha256') != reference_hash):
                    raise ValueError('현재 규칙 검사와 원본·대본 버전이 일치하지 않습니다.')
            if not isinstance(review.get('naturalness_review'), dict):
                raise ValueError('현재 규칙 검사 응답이 완전하지 않습니다.')
            refreshed.append((index, {**item, **{
                key: review[key] for key in
                ('integrity_review', 'rewrite_review', 'naturalness_review', 'quality_summary')
            }}))
        except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
            # Retain already verified rows if a later request fails. Stop this
            # batch instead of repeating requests against an unavailable service.
            raise ReviewUnavailable(str(exc), refreshed + list(valid[offset:])) from exc
    return refreshed
