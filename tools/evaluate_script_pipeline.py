"""Exercise the real script service without changing production tasks or voices.

Inputs are an explicit JSON list of {name, product, reference, video}. Receipts
make a restarted evaluation resume its existing jobs instead of submitting again.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hotpost.config import load_settings
from hotpost.studio_adapter import StudioAdapter
from hotpost.studio_top_pick import choose
from hotpost.voicebench_adapter import VoiceBenchAdapter
from dataclasses import replace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    adapter = StudioAdapter(settings)
    health = VoiceBenchAdapter(settings).default_voice_status()
    if health.get('active_requests', 0):
        raise RuntimeError('음성 작업이 끝난 뒤 대본 실측을 실행하세요.')
    VoiceBenchAdapter(settings).release_idle()
    contract = adapter.writing_contract()
    (args.output/'contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2),'utf-8')
    for case in json.loads(args.cases.read_text('utf-8')):
        receipt = args.output/(case['name']+'.json')
        if receipt.is_file():
            saved=json.loads(receipt.read_text('utf-8'))
            remote=adapter.get(saved['job_id'])
        else:
            remote=adapter.submit('script-eval-'+args.output.name+'-'+case['name'],Path(case['video']),case['reference'],
                {'product':case['product'],'evidence_mode':'benchmark','notes':'공통 대본 계약으로 자동 제작합니다.',
                 'reference_caption':case.get('post_caption',''),
                 'reference_kind':case.get('reference_kind','provided_text'),
                 'generation_key':contract['sha256']})
        receipt.write_text(json.dumps({'job_id':remote['id'],'state':remote['state']},ensure_ascii=False,indent=2),'utf-8')
        last=None
        while remote['state'] not in ('completed','failed','cancelled','interrupted'):
            key=(remote['state'],remote.get('message'))
            if key != last:
                print(case['name'],remote['id'],*key,flush=True);last=key
            time.sleep(3)
            remote=adapter.get(remote['id'])
        result={'job_id':remote['id'],'state':remote['state'],'error':remote.get('error'),'result':remote.get('result')}
        if remote['state']=='completed':
            state={'id':case['name'],'original_text':case['reference'],
                   'benchmark_analysis':remote['result'].get('benchmark',{}).get('analysis',{})}
            index,review=choose(replace(settings,data_dir=args.output/'selection'),state,list(enumerate(remote['result']['scripts'])))
            result.update(selected_index=index,selection=review)
            print(case['name'],'COMPLETED','selected',index,'review_reused',review.get('review_reused'),flush=True)
        else:
            print(case['name'],remote['state'],remote.get('error'),flush=True)
        receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')


if __name__ == '__main__':
    main()
