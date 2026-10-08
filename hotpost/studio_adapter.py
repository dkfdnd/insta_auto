"""Stable adapter name for the internal Codex writer and archived script jobs."""
import json
import time
from pathlib import Path
from .writing.contract import snapshot
from .writing.jobs import Jobs


class StudioAdapter:
    def __init__(self,settings,session=None):
        self.settings=settings
        self._jobs=None

    @property
    def jobs(self):
        if self._jobs is None:self._jobs=Jobs(self.settings.data_dir/'writing')
        return self._jobs

    def writing_contract(self):return snapshot()

    def review(self,text,reference,evidence_mode='benchmark'):
        from .writing.checks import review
        return review(text,reference,evidence_mode)

    def submit(self,production_id,video,reference,payload):
        from .source_quality import sha256_file
        if not reference.strip():raise ValueError('원본 발화가 없습니다.')
        body={**payload,'reference_script':reference,'reference_video_sha256':sha256_file(Path(video)),
              'writing_contract':self.writing_contract(),'writing_provider':'codex_internal','flow':'single-draft-v1'}
        job=self.jobs.create('script',body,production_id);self.jobs.start();return job

    def get(self,job_id):
        if not isinstance(job_id,str) or not job_id.isalnum():raise ValueError('잘못된 대본 작업 ID')
        if not job_id.startswith('codex'):
            path=self.jobs.root/'legacy'/f'{job_id}.json'
            if not path.is_file():raise ValueError('과거 대본 기록이 내재화되지 않았습니다. 기존 결과를 확인하세요.')
            return json.loads(path.read_text('utf-8'))
        job=self.jobs.get(job_id)
        if job['state'] in ('queued','running'):self.jobs.start()
        return job

    def retry(self,production_id,job_id):
        old=self.get(job_id)
        if old['state'] not in ('failed','cancelled','interrupted'):raise ValueError('실패·취소·중단 작업만 재시도할 수 있습니다.')
        if self.jobs.active_children(job_id):raise ValueError('이전 Codex 실행이 아직 진행 중입니다.')
        body={**old['payload'],'writing_contract':snapshot(old['payload'].get('generation_mode')),'writing_provider':'codex_internal','flow':'single-draft-v1'}
        job=self.jobs.create('script' if old['kind']=='script' else old['kind'],body,production_id+'-retry-'+job_id)
        self.jobs.start();return job

    def editorial(self,instruction,evidence,media=None):
        payload={'instruction':instruction,'evidence':evidence,'media':media or []}
        if evidence.get('purpose') in ('script_selection','script_revision','script_review'):
            payload['writing_contract']=self.writing_contract()
        if len(payload['media'])>128 or len(json.dumps(payload).encode())>12*1024*1024:
            raise ValueError('분석 자료가 너무 큽니다.')
        job=self.jobs.create('editorial',payload)
        # A later request may retry a transient failure once; never loop or
        # replace an in-flight job. The retry identity is itself durable.
        if job['state'] in ('failed','cancelled','interrupted') and not self.jobs.active_children(job['id']):
            job=self.jobs.create('editorial',payload,'retry-'+job['id'])
        self.jobs.start()
        return self._wait(job)['result']['value']

    def save_manual(self,text,reference,product,source_evidence,evidence_mode='benchmark'):
        job=self.jobs.create('manual',{'text':text,'reference_script':reference,'product':product,
            'source_evidence':source_evidence,'evidence_mode':evidence_mode,'writing_contract':self.writing_contract()})
        self.jobs.start();return self._wait(job)

    def _wait(self,job):
        deadline=time.monotonic()+self.settings.studio_timeout
        while time.monotonic()<deadline:
            job=self.get(job['id'])
            if job['state']=='completed':return job
            if job['state'] in ('failed','cancelled','interrupted'):
                raise RuntimeError('Codex 실행 실패: '+str(job.get('error') or job.get('message'))[:500])
            time.sleep(.5)
        raise RuntimeError('집필 대기 시간이 초과됐습니다. 재요청하면 같은 저장 작업을 확인합니다.')
