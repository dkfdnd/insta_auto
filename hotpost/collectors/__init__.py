from .base import Collector, CollectError

__all__ = ["Collector", "CollectError", "get_collector"]


def get_collector(name: str, settings):
    """이름으로 수집기 선택. 새 수집기를 추가하려면 여기에 등록하면 된다."""
    if name == "instaloader":
        from .instaloader_collector import InstaloaderCollector
        return InstaloaderCollector(settings)
    if name in ("web", "web_graphql"):
        from .web_graphql import WebGraphQLCollector
        return WebGraphQLCollector(settings)
    if name == "demo":
        from .demo import DemoCollector
        return DemoCollector(settings)
    raise ValueError(f"알 수 없는 수집기: {name}")
