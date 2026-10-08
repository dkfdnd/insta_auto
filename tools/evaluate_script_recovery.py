"""Replay completed script failures into separate recovery jobs, without TTS/render."""
import argparse
import hashlib
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from hotpost.config import load_settings
from hotpost.studio_adapter import StudioAdapter
from hotpost.studio_top_pick import choose
from hotpost.voicebench_adapter import VoiceBenchAdapter


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    settings=load_settings();adapter=StudioAdapter(settings);voice=VoiceBenchAdapter(settings)
    if voice.default_voice_status().get('active_requests',0):raise RuntimeError('음성 작업이 끝난 뒤 실행하세요.')
    voice.release_idle()
    for case in json.loads(args.jobs.read_text('utf-8')):
        path=args.output/(case['name']+'.json')
        parent=adapter.get(case['job_id'])
        before=json.dumps(parent['result'],ensure_ascii=False,sort_keys=True)
        if path.exists():remote=adapter.get(json.loads(path.read_text('utf-8'))['job_id'])
        else:remote=adapter.request('POST','/api/jobs/'+case['job_id']+'/recover-script')
        path.write_text(json.dumps({'job_id':remote['id'],'parent_job_id':case['job_id'],'state':remote['state']}),'utf-8')
        last=None
        while remote['state'] not in ('completed','failed','cancelled','interrupted'):
            status=(remote['state'],remote.get('message'))
            if status!=last:print(case['name'],remote['id'],*status,flush=True);last=status
            time.sleep(2);remote=adapter.get(remote['id'])
        value={'job_id':remote['id'],'parent_job_id':case['job_id'],'state':remote['state'],
               'result':remote.get('result'),'error':remote.get('error')}
        if remote['state']=='completed':
            state={'id':case['name'],'original_text':remote['payload']['reference_script'],
                   'benchmark_analysis':remote['result']['benchmark']['analysis']}
            index,selection=choose(replace(settings,data_dir=args.output/'selection'),state,
                                   list(enumerate(remote['result']['scripts'])))
            value.update(selected_index=index,selection=selection)
            print(case['name'],'completed',remote['result']['quality_recovery'],'selected',index,flush=True)
        value['parent_result_preserved']=(before==json.dumps(adapter.get(case['job_id'])['result'],ensure_ascii=False,sort_keys=True))
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8')


if __name__=='__main__':main()
