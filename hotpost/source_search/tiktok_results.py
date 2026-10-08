"""Read video items from the search response already fetched by TikTok's page."""
from urllib.parse import parse_qs, urlparse


def search_response_candidates(response_url, body, query):
    url = urlparse(response_url)
    if url.hostname not in ('www.tiktok.com', 'tiktok.com') or url.path not in (
            '/api/search/item/full/', '/api/search/general/full/'):
        return []
    if parse_qs(url.query).get('keyword', [''])[0] != query:
        return []  # Never attribute an older search's response to this query.
    if not isinstance(body, dict) or body.get('status_code') not in (None, 0):
        return []
    items = list(body.get('item_list') or [])
    for row in body.get('data') or []:
        if isinstance(row, dict):
            items.append(row.get('item') or row.get('item_info') or row)
    candidates = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('video'), dict):
            continue
        author = item.get('author') or {}
        user = (author.get('uniqueId') or author.get('unique_id')) if isinstance(author, dict) else ''
        video_id = str(item.get('id') or '')
        if not user or not video_id.isdigit():
            continue
        link = f'https://www.tiktok.com/@{user}/video/{video_id}'
        candidates[link] = {'url': link, 'provider': 'playwright-tiktok',
                            'title': str(item.get('desc') or '')[:240],
                            'query': query, 'match_kind': 'platform-search'}
    return list(candidates.values())
