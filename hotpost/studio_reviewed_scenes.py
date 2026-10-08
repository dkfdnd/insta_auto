"""Bind explicitly reviewed narration clauses to bounded, hashed source scenes."""
from __future__ import annotations

import copy
import math
import re


def apply_reviewed_scenes(plan, rules):
    if not isinstance(rules,list) or not rules or len(rules)>100:
        raise ValueError('검토한 장면 규칙을 확인하세요.')
    plan=copy.deepcopy(plan)
    sources={s['sha256']:s for s in plan['sources']}
    bounds={s['sha256']:max(x['end'] for x in plan['shots'] if x['sha256']==s['sha256']) for s in plan['sources']}
    for rule in rules:
        if rule.get('reviewed') is not True or rule.get('source_sha256') not in sources:
            raise ValueError('검토한 장면과 현재 소스의 해시가 다릅니다.')
        start,end=rule.get('start'),rule.get('end')
        if (type(start) not in (int,float) or type(end) not in (int,float)
            or not math.isfinite(start) or not math.isfinite(end)
            or not 0<=start<end<=bounds[rule['source_sha256']]+.001):
            raise ValueError('검토한 장면 구간이 실제 소스 범위를 벗어났습니다.')
        if rule.get('relation') not in ('direct','context') or not rule.get('evidence_frames'):
            raise ValueError('장면 검토 근거가 없습니다.')
        re.compile(rule['pattern'])
    for beat in plan['beats']:
        rule=next((r for r in rules if re.search(r['pattern'],beat['text'])),None)
        if not rule:raise ValueError('검토한 장면이 연결되지 않은 발화 구간: '+beat['text'])
        source=sources[rule['source_sha256']];sid='reviewed-'+beat['id']
        plan['shots'].append({'id':sid,'source_id':source['id'],'path':source['path'],
            'sha256':source['sha256'],'start':rule['start'],'end':rule['end'],
            'frames':list(rule['evidence_frames']),'observation':rule['reason'],
            'reviewed_by':'agent_actual_source_frames'})
        beat.update(options=[{'shot_id':sid,'relation':rule['relation'],'reason':rule['reason'],
                              'reviewed':True}],selected_shot_id=sid)
    plan['semantic_provider']='agent_actual_source_frames'
    plan['reviewed_scene_rules']=copy.deepcopy(rules)
    return plan
