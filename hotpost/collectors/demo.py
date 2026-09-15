"""샘플 데이터 수집기.

로그인 세션이 아직 없을 때 파이프라인과 웹 화면을 확인하기 위한 가짜 데이터.
계정 이름은 influencer_list.txt 의 실제 이름을 쓰지만, 수치/캡션은 모두 생성된 것이다.
리포트에는 source="demo" 로 표시되어 화면 상단에 경고 배너가 뜬다.
"""
from __future__ import annotations

import hashlib
import random
import time

from ..config import Settings
from ..models import Post, Profile
from ..observations import MetricObservation

_TOPICS = [
    ("주방 정리", ["#주방정리", "#살림템", "#정리수납"], "주방 서랍 이렇게 바꾸니까 요리 시간이 반으로 줄었어요 🍳"),
    ("욕실 청소", ["#욕실청소", "#청소꿀팁", "#살림"], "곰팡이 없는 욕실 만드는 3가지 습관, 이것만 하세요"),
    ("다이소 추천", ["#다이소", "#다이소추천템", "#가성비"], "다이소 신상 중에 진짜 쓸만한 것만 골라봤어요 (5천원 컷)"),
    ("세탁 꿀팁", ["#세탁꿀팁", "#빨래", "#살림꿀팁"], "수건 냄새 안 나게 빨래하는 법, 세제보다 중요한 건 이거"),
    ("냉장고 정리", ["#냉장고정리", "#식재료보관", "#살림"], "냉장고 정리 한 번 하고 식비 20만원 아꼈어요"),
    ("현관 인테리어", ["#현관인테리어", "#신발장", "#집꾸미기"], "좁은 현관 넓어 보이게 만드는 소품 배치"),
    ("반찬 준비", ["#밑반찬", "#주말반찬", "#집밥"], "일요일 1시간 투자로 일주일 반찬 끝내기"),
    ("이사 준비", ["#이사준비", "#이사꿀팁", "#신혼집"], "이사 전에 꼭 확인해야 할 체크리스트 10개"),
    ("옷장 정리", ["#옷장정리", "#옷정리", "#미니멀라이프"], "계절 바뀔 때 옷장 정리, 이 순서로 하면 30분이면 끝"),
    ("쿠팡 추천", ["#쿠팡추천", "#살림템추천", "#내돈내산"], "이번 달 쿠팡에서 제일 잘 산 살림템 TOP5"),
    ("아이 방", ["#아이방", "#장난감정리", "#육아템"], "장난감 정리 이렇게 하니 아이가 스스로 치워요"),
    ("에어프라이어", ["#에어프라이어", "#에프요리", "#간단요리"], "에어프라이어로 10분 만에 끝내는 야식 레시피"),
    ("환기/습도", ["#제습", "#환기", "#장마철"], "장마철 습도 잡는 법, 제습기 없이도 가능해요"),
    ("베란다", ["#베란다정리", "#베란다텃밭", "#집꾸미기"], "베란다 죽은 공간 살리는 수납 아이디어"),
]


class DemoCollector:
    name = "demo"

    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch(self, username: str, limit: int, existing: dict[str, Post] | None = None) -> tuple[Profile, list[Post], list[MetricObservation]]:
        seed = int(hashlib.md5(username.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        followers = int(rng.choice([8_000, 25_000, 60_000, 120_000, 300_000]) * rng.uniform(0.6, 1.6))
        profile = Profile(
            username=username, user_id=str(seed), full_name=username.replace("_", " ").title(),
            followers=followers, following=rng.randint(100, 900), media_count=rng.randint(200, 2000),
            biography="(샘플 데이터) 살림/리빙 인플루언서",
            profile_pic_url="", is_private=False,
        )
        base_views = followers * rng.uniform(0.8, 3.0)
        base_likes = followers * rng.uniform(0.01, 0.04)
        base_comments = max(3, base_likes * rng.uniform(0.01, 0.05))
        now = int(time.time())
        posts = []
        t = now - rng.randint(2, 30) * 3600
        for i in range(limit):
            kind = "reel" if rng.random() < 0.75 else rng.choice(["image", "carousel"])
            topic, tags, cap = rng.choice(_TOPICS)
            # 로그정규 분포로 자연스러운 편차 + 가끔 '터진' 게시물
            burst = rng.choice([1, 1, 1, 1, 1, 1, 1, 1.6, 2.5, 4.5, 8.0]) if i < 12 else rng.choice([1, 1, 1, 1.5, 3])
            noise = lambda: rng.lognormvariate(0, 0.35)  # noqa: E731
            age_h = (now - t) / 3600
            maturity = min(1.0, 0.35 + 0.65 * age_h / 72)
            views = int(base_views * burst * noise() * maturity) if kind == "reel" else None
            likes = int(base_likes * burst * noise() * maturity * (1.0 if kind == "reel" else 1.3))
            comments = int(base_comments * (burst ** 1.2) * noise() * maturity)
            code = "DEMO" + hashlib.md5(f"{username}{i}".encode()).hexdigest()[:7]
            posts.append(Post(
                shortcode=code, username=username, taken_at=t, kind=kind,
                likes=likes, comments=comments, views=views,
                caption=f"{cap}\n\n{' '.join(tags)} #{username}",
                hashtags=[h[1:].lower() for h in tags], thumbnail_url="", video_duration=(rng.randint(15, 60) if kind == "reel" else None),
                media_id=str(seed + i),
            ))
            t -= int(rng.uniform(0.6, 2.2) * 86400)
        observations = [MetricObservation(p.shortcode, now, now, True, p.views, p.likes, p.comments,
                                          "demo", age_hours=max(0, (now - p.taken_at) / 3600))
                        for p in posts if p.is_video]
        return profile, posts, observations
