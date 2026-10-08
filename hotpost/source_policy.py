"""Versioned acquisition requirements; saved completed runs keep their contract."""
from copy import deepcopy
from urllib.parse import urlparse


def current_policy(settings=None):
    return {'version': 2, 'minimum_total': max(10, getattr(settings, 'source_min_usable', 10)),
            'platform_minimums': {'tiktok': max(5, getattr(settings, 'source_tiktok_min_usable', 5))}}


def run_policy(state, target=10):
    run = next((r for r in state.get('runs', []) if r['id'] == state.get('run_id')), {})
    # A saved run without a policy predates platform quotas. Reading it must
    # not migrate its completion or silently reinterpret its old inventory.
    policy = run.get('source_policy') if run else state.get('source_policy')
    return deepcopy(policy or {'version': 1, 'minimum_total': state.get('source_goal', {}).get('target', target),
                               'platform_minimums': {}})


def adopt_policy(state, settings=None):
    policy = (owned_policy() if state.get('creation_mode') == 'self_shot' else current_policy(settings))
    state['source_policy'] = deepcopy(policy)
    run = next((r for r in state.get('runs', []) if r['id'] == state.get('run_id')), None)
    if run and run.get('status') != 'completed':
        run['source_policy'] = deepcopy(policy)
    return policy


def owned_policy():
    return {'version':'self-shot-v1', 'minimum_total':1, 'maximum_total':20,
            'platform_minimums':{}, 'owned_only':True}


def source_platform(source):
    host = (urlparse(source.get('origin_url') or source.get('original_url') or source.get('url') or '').hostname or '').lower()
    for name, domains in {'tiktok': ('tiktok.com',), 'douyin': ('douyin.com',),
                          'xiaohongshu': ('xiaohongshu.com', 'xhslink.com'),
                          'instagram': ('instagram.com',), 'youtube': ('youtube.com', 'youtu.be'),
                          'bilibili': ('bilibili.com',), 'stock': ('pexels.com', 'vimeo.com')}.items():
        if any(host == d or host.endswith('.' + d) for d in domains):
            return name
    return 'other'


def goal_message(goal):
    text = f"전체 {goal['count']}/{goal['target']}개"
    for platform, coverage in goal.get('platform_targets', {}).items():
        text += f" · {'TikTok' if platform == 'tiktok' else platform} {coverage['usable']}/{coverage['target']}개"
    return text
