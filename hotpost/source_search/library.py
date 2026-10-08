"""Discover stored footage across references; never carry old editing approval."""
import json
import re
from functools import lru_cache
from pathlib import Path

from .models import Candidate
from ..source_queries import PRODUCTS
from ..source_urls import canonical_video_key, video_url

STOP = set('a an the and or of for to with in on new best review video demonstration demo '
           'tutorial diy portable small large mini multifunctional product outfit fashion '
           'women womens men mens unboxing try showing use using design preparation '
           'home family brand set item items accessory accessories easy simple'.split())
FAMILIES = [(*names, *aliases) for *names, aliases in PRODUCTS] + [
    ('운동화', '스니커즈', 'sneakers', 'running shoes', '运动鞋',
     'new balance 1906r', 'nb 1906r', 'new balance 9060', 'newbalance9060'),
    ('가디건', 'cardigan', '开衫', '開衫'),
    ('피아노', 'piano', '钢琴'),
    ('비즈 키링', 'beaded keychain', 'beaded clover', '串珠钥匙扣'),
    # Stored captions often compress the product into model/hashtag text.
    # These propose wristwatch footage; they do not prove the same model.
    ('손목시계', 'wristwatch', '手表', '카시오 시계', 'casio watch',
     'casio aq-230', 'casiowatches', 'vintagewatch', 'aq230', 'analog-digital'),
]
TITLE_ALIASES = {
    '다진 마늘 준비': ('minched garlic', 'freezing garlic', '大蒜'),
    '비즈 키링': ('네잎클로버', '네잎크로버', '행운키링', 'four leaf clover', '四叶草'),
    '운동화': ('newbalances9060',),
}
FAMILIES = [(*family, *TITLE_ALIASES.get(family[0], ())) for family in FAMILIES]


def contains(text, phrase):
    phrase=phrase.lower().strip()
    if not phrase:
        return False
    if re.fullmatch(r'[a-z0-9 ]+',phrase):
        return bool(re.search(r'(?<![a-z0-9])'+re.escape(phrase)+r'(?![a-z0-9])',text))
    if ' ' in phrase and re.search(r'[가-힣]', phrase):
        # Korean hashtags omit word spacing; the actual subject stays the same.
        return bool(re.search(r'\s*'.join(re.escape(w) for w in phrase.split()), text))
    return phrase in text


def families(text):
    return {i for i,aliases in enumerate(FAMILIES) if any(contains(text,a) for a in aliases)}


def match_score(products, body):
    """Exact subject vocabulary suggests candidates, not visible functionality."""
    body=body.lower()
    desired=' '.join(products).lower()
    shared=families(desired) & families(body)
    score=4. if shared else 0.
    for name in products:
        name=name.lower().strip()
        words=[w for w in re.findall(r'[a-z0-9]+',name) if w not in STOP and len(w)>2]
        if not words and not re.search(r'[가-힣\u3400-\u9fff]',name):
            continue
        if len(name)>=4 and contains(body,name):
            score=max(score,8.)
        if words and contains(body,words[-1]):
            common=sum(contains(body,w) for w in words)
            if common==len(words):
                score=max(score,5.+min(common,3))
    return score


@lru_cache(maxsize=512)
def manifest_records(path, modified, size):
    # mtime+size invalidates checkpoint manifests as new downloads are saved.
    try:
        data=json.loads(Path(path).read_text('utf-8'))
        if not isinstance(data,dict) or not isinstance(data.get('candidates',[]),list):
            return []
        records=[]
        for item in data.get('candidates',[]):
            if not isinstance(item,dict):
                continue
            url=item.get('original_url') or item.get('url','')
            file=item.get('original_downloaded_file') or item.get('downloaded_file')
            if not file or not video_url(url):
                continue
            if 'download_failed' in (item.get('rejection_reasons') or []):
                continue
            # A different_core_function rejection is relative to the old
            # reference. It neither approves nor vetoes the new reference.
            review=item.get('functional_review')
            actions=review.get('observed_actions',[]) if isinstance(review,dict) else []
            actions=actions if isinstance(actions,list) else []
            observation=[a for a in actions
                         if not str(a).lower().lstrip().startswith(('참조','원본','레퍼런스','reference'))]
            # The old search query describes the desired reference, not
            # necessarily this candidate (searches also return wrong products).
            body=' '.join([str(item.get('title','')),
                           *[str(a) for a in observation]])
            records.append({'shortcode':data.get('shortcode',''), 'url':url,
                'title':str(item.get('title','')), 'body':body,
                'file':str(Path(path).parent/file), 'selected':bool(item.get('selected_for_zip')),
                'rights':item.get('rights','unknown-check-before-reuse')})
        return records
    except (OSError,ValueError,TypeError):
        return []


def discover(settings, shortcode, query_plan, limit):
    from ..source_collection_access import disabled_platforms
    root=settings.source_dir.resolve()
    disabled=disabled_platforms(settings)
    products=[str(p[k]) for p in query_plan.get('products',[]) if isinstance(p,dict)
              for k in ('ko','en','zh') if p.get(k)]
    if not products:
        products=[str(q.get('query','')) for q in query_plan.get('query_details',[]) if isinstance(q,dict)]
    if not products or limit<=0:
        return []
    ranked=[]
    for path in root.glob('*/manifest.json'):
        try:
            stat=path.stat()
        except OSError:
            continue
        for row in manifest_records(str(path),stat.st_mtime_ns,stat.st_size):
            # Include historical same-reference files as proposals too. The
            # discovery caller excludes URLs already examined in this batch,
            # and every new proposal still needs current visual validation.
            try:
                file=Path(row['file']).resolve()
                valid=(file.is_relative_to(root) and file.name!='reference.mp4'
                       and file.suffix.lower() in {'.mp4','.webm','.mkv','.mov'}
                       and file.is_file() and file.stat().st_size)
            except (OSError,ValueError):
                valid=False
            if not valid:
                continue
            score=match_score(products,row['body'])
            if not score:
                continue
            candidate=Candidate(url=row['url'],provider='source-library',title=row['title'],
                query=products[0][:120],match_kind='library-candidate',rights=row['rights'],
                cached_path=str(file))
            if candidate.platform in disabled:
                continue
            ranked.append((candidate.platform=='tiktok',score,row['selected'],candidate))
    ranked.sort(key=lambda r:r[:3],reverse=True)
    result=[];seen=set()
    for _,_,_,candidate in ranked:
        key=canonical_video_key(candidate.url)
        if key in seen:
            continue
        result.append(candidate);seen.add(key)
        if len(result)>=limit:
            break
    return result
