"""Candidate discovery with injectable provider services and shortlist-first routing."""
from ..source_urls import canonical_video_key
from ..source_queries import platform_queries, language
from .strategy import fresh_queries


def discover(settings, shortcode, frames, queries, query_plan, vision_candidates, root,
             previous_searches, exclude_urls, progress, services, deferred=None):
    # Known public URLs still pass the same download, duplicate and visual gates.
    # Probe new URLs first; when exhausted the next round resumes discovery.
    used = {canonical_video_key(url) for url in exclude_urls or [] if url}
    from ..source_collection_access import disabled_platforms
    disabled = disabled_platforms(settings)
    cached = getattr(services, 'search_local_cache', lambda *args: [])(settings, shortcode, settings.source_max_candidates)
    from .library import discover as library_candidates
    library = library_candidates(settings, shortcode, query_plan, settings.source_max_candidates)
    pools = [('deferred-candidates', deferred or []),
             ('operator-shortlist', services.search_local_hints(settings, shortcode)),
             ('local-cache', cached), ('source-library', library)]
    shortlist, shortlist_audit, seen = [], [], set(used)
    for provider, candidates in pools:
        added = 0
        for candidate in candidates:
            identity = canonical_video_key(candidate.url)
            if identity in seen or candidate.platform in disabled:
                continue
            shortlist.append(candidate)
            seen.add(identity)
            added += 1
        if added:
            shortlist_audit.append({'provider':provider, 'query':'', 'status':'results', 'candidates':added})
    tiktok_preference = max(5, settings.source_tiktok_min_usable)
    if shortlist:
        label = '저장된 소스·공개' if any(row['provider'] in {'local-cache','source-library'} for row in shortlist_audit) else '시간 부족으로 미검증한' if deferred else '확보한 공개'
        progress(f"{label} 후보 {len(shortlist)}개부터 검증하는 중", 42)
        browser = {"candidates": [], "terms": [], "notes": []}
        return shortlist, queries, browser, shortlist_audit, tiktok_preference
    browser_result = {"candidates": [], "terms": [], "notes": []}
    strategy = query_plan.get('search_strategy')
    allowed = strategy['routes'] if strategy else None
    search_audit = []
    def enabled(provider):
        return allowed is None or provider in allowed
    def run_browser():
        nonlocal browser_result
        if settings.source_browser_search:
            from ..browser_search import browser_search
            options = {'routes':allowed} if strategy else {}
            browser_result = browser_search(settings, frames, queries, settings.source_max_candidates, root / "browser_debug",
                                            previous_searches=[*(previous_searches or []), *search_audit],
                                            progress=lambda msg: progress(msg, 32), **options)
            search_audit.extend(browser_result.get('searches', []))
    if strategy:
        search_audit.extend({'provider':provider,'query':'','status':'strategy_skipped','candidates':0,'reason':reason}
                            for provider, reason in strategy['skipped_routes'].items())
    defer_browser = bool(allowed and allowed[0] in {'youtube','bing','duckduckgo'})
    if not defer_browser:
        run_browser()
    # Keep the grounded pool even after all routes exhaust it. Image labels
    # must not silently replace the actual subject with background objects.
    queries = list(dict.fromkeys(q for q in queries if q.strip()))
    candidates = list(vision_candidates)
    if not defer_browser:
        candidates += [services.Candidate(**item) for item in browser_result["candidates"]]
    def available(pool, provider, maximum, language_provider=None):
        selected = fresh_queries(pool, provider, [*(previous_searches or []), *search_audit])
        if not selected:
            search_audit.append({'provider':provider, 'query':'', 'status':'query_exhausted' if pool else 'no_supported_queries', 'candidates':0})
        return platform_queries(selected, language_provider or provider, maximum)
    progress("공개 웹 검색 결과를 합치는 중", 42)
    per_platform = max(4, settings.source_max_candidates // 5)
    # Ordinary indexed public TikTok links supplement low-yield in-site search.
    tiktok_queries = platform_queries(queries, 'tiktok', len(queries))
    indexed_tiktok_queries = [q + ' site:tiktok.com/@ inurl:video' for q in tiktok_queries]
    tiktok_preference = max(5, settings.source_tiktok_min_usable)
    tiktok_candidates = []
    if enabled('youtube') and defer_browser:
        candidates += services.search_youtube(available(queries, 'youtube', settings.source_queries_per_platform), per_platform,
                                      settings.source_browser_cookie_file, search_audit, settings.source_ytdlp_js_runtime)
    if enabled('duckduckgo') and enabled('tiktok'):
        tiktok_candidates = services.search_web(available(indexed_tiktok_queries, 'duckduckgo', 3, 'tiktok'), min(settings.source_max_candidates, tiktok_preference * 3), search_audit)
    if enabled('bing') and enabled('tiktok') and not any(c.platform == 'tiktok' for c in tiktok_candidates):
        tiktok_candidates += services.search_bing(available(indexed_tiktok_queries, 'bing', 3, 'tiktok'), min(settings.source_max_candidates, tiktok_preference * 3), search_audit)
    candidates += [c for c in tiktok_candidates if c.platform == 'tiktok']
    web_queries = queries
    candidates += services.search_local_cache(settings, shortcode, per_platform)
    candidates += services.search_local_hints(settings, shortcode)
    if enabled('duckduckgo'):
        candidates += services.search_web(available(web_queries, 'duckduckgo', settings.source_queries_per_platform, 'youtube'), per_platform, search_audit)
    if enabled('bing'):
        candidates += services.search_bing(available(web_queries, 'bing', settings.source_queries_per_platform, 'youtube'), per_platform, search_audit)
    # Public product clips often retain the exact object when broad social
    # queries return unrelated storage products. The same CLIP/OCR gates apply.
    vendor_queries = [q + ' site:lazada.com.ph/videodetail/' for q in queries if language(q) == 'en']
    if enabled('bing') and (not strategy or strategy['vendor_search']):
        candidates += services.search_bing(available(vendor_queries, 'bing', 2), min(4, per_platform), search_audit)
    if enabled('youtube') and not defer_browser:
        candidates += services.search_youtube(available(web_queries, 'youtube', settings.source_queries_per_platform), per_platform,
                                 settings.source_browser_cookie_file, search_audit, settings.source_ytdlp_js_runtime)
    if defer_browser:
        run_browser()
        candidates += [services.Candidate(**item) for item in browser_result['candidates']]
    candidates += services.search_pexels(settings, available(queries, 'pexels', 1, 'youtube'), per_platform, search_audit)
    candidates = [c for c in candidates if c.platform not in disabled]
    return candidates, queries, browser_result, search_audit, tiktok_preference
