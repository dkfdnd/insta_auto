"""'터진 게시물' 판정 로직.

핵심 아이디어: 절대 수치가 아니라 **그 계정의 평소 성과 대비 배수**로 본다.
팔로워 3만 계정의 10만 뷰와 팔로워 100만 계정의 10만 뷰는 의미가 다르기 때문.

게시물 p 에 대해
  1. 같은 계정의 다른 최근 게시물(같은 유형 우선)의 중앙값 = baseline
  2. 게시 후 시간이 짧으면 반응이 덜 쌓였으므로 baseline 을 maturity(0.35~1.0)로 줄여서 비교
  3. ratio_x = (p.x + 1) / (baseline_x * maturity + 1)      (x = views / likes / comments)
  4. 종합 배수 = 2 ** Σ w_x · log2(ratio_x)
       릴스/동영상: 조회수 0.5, 댓글 0.3, 좋아요 0.2
       사진/캐러셀: 좋아요 0.6, 댓글 0.4
  5. 배수 ≥ 1.8 → 🔥, ≥ 3 → 🔥🔥, ≥ 5 → 🔥🔥🔥
"""
from __future__ import annotations

import math
import re
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .config import Settings
from .models import Post, Profile
from .criteria import defaults

# ---------------------------------------------------------------- scoring

@dataclass
class Scored:
    post: Post
    baseline: dict            # {"likes": float, "comments": float, "views": float|None, "peers": int}
    ratios: dict              # {"likes": float, "comments": float, "views": float|None}
    multiplier: float
    tier: int                 # 0~3
    rank_score: float
    age_hours: float
    maturity: float
    flags: list[str] = field(default_factory=list)
    confidence: str = "high"
    velocity: dict | None = None   # 스냅샷이 2개 이상일 때 시간당 증가량


def _median(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return float(statistics.median(xs)) if xs else None


def _ratio(value: float | None, base: float | None, maturity: float) -> float | None:
    if value is None or base is None:
        return None
    return (value + 1.0) / (base * maturity + 1.0)


def score_account(posts: list[Post], settings: Settings, now: int | None = None,
                  snapshots: dict[str, list[dict]] | None = None,
                  criteria: dict | None = None, followers: int = 0) -> list[Scored]:
    now = now or int(time.time())
    c = criteria or defaults(settings)
    out: list[Scored] = []
    for p in posts:
        older = [q for q in posts if q.taken_at < p.taken_at]
        same_kind = [q for q in older if q.is_video == p.is_video]
        other_kind = [q for q in older if q.is_video != p.is_video]
        peer_limit = min(30, max(1, settings.posts_per_account))
        peers = same_kind[:peer_limit]
        supplemented = len(peers) < settings.min_peers_for_baseline
        if supplemented:
            peers += other_kind[:peer_limit - len(peers)]
        base_likes = _median([q.likes for q in peers])
        base_comments = _median([q.comments for q in peers])
        base_views = _median([q.views for q in peers if q.is_video]) if p.is_video else None
        if p.is_video and (base_views is None or base_views <= 0):
            base_views = None

        age_h = max(0.0, (now - p.taken_at) / 3600.0)
        maturity = min(1.0, 0.35 + 0.65 * age_h / settings.maturity_hours)

        m = maturity if c["maturity"] else 1.0
        r_likes = _ratio(p.likes, base_likes, m) or 1.0
        r_comments = _ratio(p.comments, base_comments, m) or 1.0
        r_views = _ratio(p.views, base_views, m) if p.is_video else None

        if r_views is not None:
            names = ("wvViews", "wvComments", "wvLikes")
            ratios = (r_views, r_comments, r_likes)
        else:
            names = ("wiLikes", "wiComments")
            ratios = (r_likes, r_comments)
        total_weight = sum(c[name] for name in names)
        weights = [(ratio, c[name] / total_weight) for ratio, name in zip(ratios, names)]
        log_mult = sum(w * math.log2(max(r, 1e-6)) for r, w in weights)
        multiplier = 2 ** log_mult

        engagement = (p.likes or 0) + (p.comments or 0) * 5 + (p.views or 0) / 50
        if engagement < c["minEng"] or not peers:
            multiplier = min(multiplier, 1.0)

        if multiplier >= c["t3"]:
            tier = 3
        elif multiplier >= c["t2"]:
            tier = 2
        elif multiplier >= c["t1"]:
            tier = 1
        else:
            tier = 0

        # 계정 간 순위: 배수를 기본으로 하되 절대 규모를 약간 반영(작은 계정의 우연한 튐 완화)
        rank_score = multiplier * (0.6 + 0.4 * min(1.0, math.log10(engagement + 1) / 5.0))

        flags = []
        if r_comments >= 2.5 and (p.comments or 0) >= 5:
            flags.append("comments_spike")
        if r_views is not None and r_views >= 2.5:
            flags.append("views_spike")
        if r_likes >= 2.5:
            flags.append("likes_spike")
        if age_h <= 48:
            flags.append("fresh")
        confidence = "high"
        if supplemented or len(peers) < settings.min_peers_for_baseline or age_h < 12:
            confidence = "low"
        elif len(peers) < settings.min_peers_for_baseline * 2 or age_h < 24:
            confidence = "medium"

        confidence_rank = {"low": 0, "medium": 1, "high": 2}
        gated = (
            (c["followersMin"] and followers < c["followersMin"])
            or (c["followersMax"] and followers > c["followersMax"])
            or (c["confidence"] != "all" and confidence_rank[confidence] < confidence_rank[c["confidence"]])
            or (c["minRatioViews"] and (r_views is None or r_views < c["minRatioViews"]))
            or (c["minRatioComments"] and r_comments < c["minRatioComments"])
            or (c["minRatioLikes"] and r_likes < c["minRatioLikes"])
            or (c["minViews"] and (p.views is None or p.views < c["minViews"]))
            or (c["minComments"] and (p.comments is None or p.comments < c["minComments"]))
            or (c["minLikes"] and (p.likes is None or p.likes < c["minLikes"]))
        )
        if gated:
            tier = 0
            flags.append("criteria_gate")

        caption = p.caption.lower()
        for flag, words in {
            "ad_candidate": ("광고", "#ad", "paid partnership"),
            "sponsored_candidate": ("협찬", "제공받", "sponsored"),
            "group_buy_candidate": ("공동구매", "공구", "group buy"),
            "event_candidate": ("이벤트", "추첨", "giveaway"),
        }.items():
            if any(word in caption for word in words):
                flags.append(flag)

        velocity = _velocity((snapshots or {}).get(p.shortcode, []))
        if velocity and velocity.get("hours", 0) >= 3:
            flags.append("rising" if velocity.get("per_hour_score", 0) > 0 else "steady")

        out.append(Scored(
            post=p,
            baseline={"likes": base_likes, "comments": base_comments, "views": base_views,
                      "peers": len(peers), "same_kind_peers": len(same_kind[:peer_limit]),
                      "supplemented": supplemented},
            ratios={"likes": r_likes, "comments": r_comments, "views": r_views},
            multiplier=multiplier, tier=tier, rank_score=rank_score, age_hours=age_h, maturity=maturity,
            flags=flags, confidence=confidence, velocity=velocity,
        ))
    return out


def _velocity(snaps: list[dict]) -> dict | None:
    if len(snaps) < 2:
        return None
    first, last = snaps[0], snaps[-1]
    hours = (last["collected_at"] - first["collected_at"]) / 3600.0
    if hours < 0.5:
        return None
    d_likes = (last["likes"] or 0) - (first["likes"] or 0)
    d_comments = (last["comments"] or 0) - (first["comments"] or 0)
    d_views = ((last["views"] or 0) - (first["views"] or 0)) if last.get("views") is not None else None
    return {
        "hours": round(hours, 1),
        "likes_per_hour": round(d_likes / hours, 2),
        "comments_per_hour": round(d_comments / hours, 2),
        "views_per_hour": (round(d_views / hours, 1) if d_views is not None else None),
        "per_hour_score": round((d_likes + d_comments * 5 + (d_views or 0) / 50) / hours, 2),
        "snapshots": len(snaps),
    }


# ---------------------------------------------------------------- topics

_TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{3,}|[0-9]+[가-힣A-Za-z]+")
_PARTICLES = ("에서는", "으로는", "이라고", "하는데", "했어요", "해요", "합니다", "입니다", "에서", "으로", "에게", "한테", "까지", "부터",
              "처럼", "보다", "이랑", "이나", "은", "는", "이", "가", "을", "를", "에", "의", "도", "로", "과", "와", "랑", "만", "요")
_STOP = set("""
그리고 그래서 하지만 정말 진짜 너무 완전 이거 저거 그거 이건 저건 그건 여기 저기 거기 오늘 내일 어제 지금 우리 제가 저는 저도 나는 나도
있어요 없어요 있는 없는 하는 하면 해서 했다 한다 하고 하는데 하니까 되는 되면 됩니다 같아요 같은 위해 통해 대한 때문 경우 정도 이렇게 그렇게
바로 다시 계속 조금 많이 아주 매우 가장 제일 더 덜 꼭 좀 안 못 잘 또 등 및 중 후 전 때 분 개 번 년 월 일 시 것 수 거 게 데 걸 건
영상 게시물 댓글 좋아요 팔로우 팔로워 링크 프로필 릴스 인스타 인스타그램 광고 협찬 쿠팡 파트너스 활동 일환 수수료 제공 받습니다 받을
만드 만들 하나 이제 오늘 요즘 매일 사용 제품 태그 클릭 구매 확인 추천 이거 이런 저런 그런 어떤 무슨 근데 그냥 사실 일단 혹시 다들 여러분
필요 가능 걱정 생각 시간 사람 정도 경우 방법 이유 문제 느낌 마음 하루 이번 다음 처음 마지막 이후 이전 부분 전체 최고 모두 다양 여러 저희 자기 자신 본인 분들
오류 dm 메시지 발송 완벽 활용 유지 대신 평소 편안 고급 궁금 답변 자동 신청 요청 무료 할인 특가 판매 구입 가격 배송 주문 링크 태그 클릭 스토리 하이라이트 이벤트 당첨 선물 감사 안녕 소통 일상 기록 사진 촬영 영상 이유 순간 느낌 마음 정보 내용 준비 시작 완성 마무리 소개 공유 참고 문의 이벤트 댓글 저장 팔로우 좋아요 알림 계정 채널 링크 프로필 하단 상단 아래 위쪽 오늘 이번주 지난주
the and for with this that you your are from have has was were not but can all more
""".split())


def _stem(tok: str) -> str:
    for p in _PARTICLES:
        if tok.endswith(p) and len(tok) - len(p) >= 2:
            return tok[: -len(p)]
    return tok


_kiwi = None


def _nouns(text: str) -> list[str]:
    """캡션에서 명사(고유명사/외래어 포함)를 뽑는다. kiwipiepy 가 있으면 형태소 분석, 없으면 정규식 근사."""
    global _kiwi
    if _kiwi is None:
        try:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
        except Exception:  # noqa: BLE001
            _kiwi = False
    if _kiwi:
        out = []
        for tok in _kiwi.tokenize(text):
            if tok.tag in ("NNG", "NNP", "SL") and len(tok.form) >= 2:
                out.append(tok.form.lower())
            else:
                out.append(None)  # 구(句) 경계 표시
        return out
    return [_stem(t.lower()) for t in _TOKEN_RE.findall(text)]


def _terms(text: str) -> set[str]:
    """단일 명사 + 인접 명사 2어절(예: '주방 정리')."""
    toks = _nouns(text)
    terms: set[str] = set()
    prev = None
    for t in toks:
        if t is None or t in _STOP or t.isdigit():
            prev = None
            continue
        terms.add(t)
        if prev:
            terms.add(prev + " " + t)
        prev = t
    return terms


def _norm_line(line: str) -> str:
    return re.sub(r"[^가-힣a-z0-9]", "", line.lower())


def _boilerplate_lines(captions: list[str], min_posts: int = 3) -> set[str]:
    """여러 게시물에 똑같이 반복되는 줄('제품 정보는 댓글에', '팔로우해야 DM 발송' 등)을 상용구로 본다."""
    cnt = Counter()
    for cap in captions:
        for ln in set(_norm_line(x) for x in cap.splitlines()):
            if len(ln) >= 6:
                cnt[ln] += 1
    return {ln for ln, n in cnt.items() if n >= min_posts}


def post_terms(posts: list[Post]) -> dict[str, list[str]]:
    """게시물별 캡션 키워드(상용구 제거 후). 웹 화면에서 기준을 바꿔도 주제를 다시 계산할 수 있게 리포트에 싣는다."""
    boiler = _boilerplate_lines([p.caption for p in posts])
    out = {}
    for p in posts:
        body = "\n".join(ln for ln in p.caption.splitlines() if _norm_line(ln) not in boiler)
        body = re.sub(r"#\S+|https?://\S+", " ", body)
        out[p.shortcode] = sorted(_terms(body))
    return out


def extract_topics(scored: list[Scored], settings: Settings) -> list[dict]:
    """핫 게시물의 해시태그/캡션 키워드를 모아 '오늘의 주제'를 만든다.

    - 등급 가중치: 🔥1 · 🔥🔥2 · 🔥🔥🔥3, 일반 게시물 0.15
    - 같은 계정 안에서 반복되는 상용구(예: '제품은 태그 클릭')가 주제로 올라오지 않도록,
      캡션 키워드는 계정당 한 번만 가중치를 준다.
    """
    weight = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    accounts: dict[str, set[str]] = defaultdict(set)
    kind: dict[str, str] = {}
    per_account_seen: dict[tuple[str, str], bool] = {}
    boiler = _boilerplate_lines([s.post.caption for s in scored])
    for s in sorted(scored, key=lambda x: x.multiplier, reverse=True):
        if s.age_hours > settings.recent_days * 24:
            continue
        w = {0: 0.15, 1: 1.0, 2: 2.0, 3: 3.0}[s.tier]
        user = s.post.username
        for h in dict.fromkeys(s.post.hashtags):
            if h == user.lower():
                continue
            key = "#" + h
            weight[key] += w
            kind[key] = "hashtag"
            examples[key].append(s.post.shortcode)
            accounts[key].add(user)
        body = "\n".join(ln for ln in s.post.caption.splitlines() if _norm_line(ln) not in boiler)
        body = re.sub(r"#\S+|https?://\S+", " ", body)
        for t in _terms(body):
            kind.setdefault(t, "keyword")
            examples[t].append(s.post.shortcode)
            accounts[t].add(user)
            if per_account_seen.get((user, t)):
                weight[t] += w * 0.1   # 같은 계정의 반복 언급은 아주 약하게만
            else:
                per_account_seen[(user, t)] = True
                weight[t] += w * (1.1 if " " in t else 0.8)
    topics = []
    for key, w in weight.most_common(settings.top_topics * 4):
        n_acc = len(accounts[key])
        if kind[key] == "keyword" and n_acc < 2:
            continue                      # 키워드는 최소 2개 계정에서 등장해야 '주제'
        if w < 1.0 and n_acc < 2:
            continue
        topics.append({
            "label": key, "kind": kind[key], "score": round(w, 2),
            "posts": len(dict.fromkeys(examples[key])), "accounts": n_acc,
            "examples": list(dict.fromkeys(examples[key]))[:8],
        })
        if len(topics) >= settings.top_topics:
            break
    return topics
