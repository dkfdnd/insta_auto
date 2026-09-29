from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hotpost.accounts import AccountRegistry
from hotpost.config import Settings
from hotpost.models import Post
from hotpost.sources import load_usernames
from hotpost.storage import Storage


def registry(tmp_path, file=None, pc='local'):
    return AccountRegistry(Settings(data_dir=tmp_path/pc, influencer_file=file or tmp_path/'influencer_list.txt'))


def db_names(reg):
    store=Storage(reg.settings.db_path)
    try:
        return [r['username'] for r in store.managed_accounts()]
    finally:
        store.close()


def test_web_changes_roundtrip_to_another_pc_without_sharing_notes(tmp_path):
    file=tmp_path/'influencer_list.txt'
    file.write_text('@first\n@second\n',encoding='utf-8')
    a=registry(tmp_path,file); b=registry(tmp_path,file,pc='remote')
    assert a.usernames()==b.usernames()==['first','second']
    a.add('@third','이 PC 개인 메모')
    assert load_usernames(file)==b.usernames()==['first','second','third']
    assert '개인 메모' not in file.read_text('utf-8')
    assert b.list()[2]['note']==''
    b.add('@first','원격 PC 메모')
    a.delete('second')
    assert b.usernames()==['first','third']
    assert b.list()[0]['note']=='원격 PC 메모'
    assert a.list()[1]['note']=='이 PC 개인 메모'


def test_pulled_membership_and_order_apply_without_server_restart(tmp_path):
    reg=registry(tmp_path)
    reg.add('first','보존할 메모');reg.add('second')
    store=Storage(reg.settings.db_path)
    store.upsert_posts([Post('fixture','first',123,'image',likes=4,comments=1)])
    store.close()
    reg.settings.influencer_file.write_text('@second\n@newone\n',encoding='utf-8')
    assert reg.usernames()==['second','newone']
    store=Storage(reg.settings.db_path)
    assert len(store.posts_for('first'))==1
    store.close()
    backups=list((reg.settings.data_dir/'account-imports').glob('*.json'))
    assert backups and '보존할 메모' in backups[0].read_text('utf-8')
    reg.settings.influencer_file.write_text('@newone\n@second\n',encoding='utf-8')
    assert reg.usernames()==['newone','second']
    reg.add('last')
    assert reg.usernames()==['newone','second','last']


@pytest.mark.parametrize('bad',['','\n# accidentally empty\n','@first\n<<<<<<< HEAD\n@second\n=======\n','@first\nnot a username\n'])
def test_invalid_or_conflicted_file_never_deletes_previous_accounts(tmp_path,bad):
    reg=registry(tmp_path);reg.add('first')
    reg.settings.influencer_file.write_text(bad,encoding='utf-8')
    with pytest.raises(ValueError):reg.list()
    with pytest.raises(ValueError):reg.add('second')
    assert db_names(reg)==['first']
    assert reg.settings.influencer_file.read_text('utf-8')==bad
    # Constructing the registry must not crash server startup.
    registry(tmp_path)


def test_explicit_empty_list_persists_and_missing_file_preserves_db(tmp_path):
    reg=registry(tmp_path);reg.add('first')
    reg.settings.influencer_file.unlink()
    assert reg.usernames()==['first']
    reg.add('second')
    assert load_usernames(reg.settings.influencer_file)==['first','second']
    reg.delete('first');reg.delete('second')
    assert registry(tmp_path).usernames()==[]
    assert 'empty-list' in reg.settings.influencer_file.read_text('utf-8')


def test_file_publication_failure_rolls_back_db(tmp_path,monkeypatch):
    from hotpost import accounts
    reg=registry(tmp_path);reg.add('first')
    before=reg.settings.influencer_file.read_bytes()
    def fail(*args):raise PermissionError('read only')
    monkeypatch.setattr(accounts.os,'replace',fail)
    with pytest.raises(PermissionError):reg.add('second')
    assert reg.settings.influencer_file.read_bytes()==before
    assert db_names(reg)==['first']
    assert not list(tmp_path.glob('*.tmp'))


def test_concurrent_registry_instances_keep_all_changes(tmp_path):
    reg=registry(tmp_path);reg.add('first')
    def add(i):registry(tmp_path).add(f'account_{i}')
    with ThreadPoolExecutor(max_workers=4) as executor:list(executor.map(add,range(8)))
    assert set(reg.usernames())=={'first',*(f'account_{i}' for i in range(8))}
    assert set(load_usernames(reg.settings.influencer_file))==set(reg.usernames())


def test_external_change_during_save_is_not_overwritten(tmp_path,monkeypatch):
    reg=registry(tmp_path);reg.add('first')
    before=reg._write
    def race(expected,names):
        reg.settings.influencer_file.write_text('@first\n@pulled\n',encoding='utf-8')
        return before(expected,names)
    monkeypatch.setattr(reg,'_write',race)
    with pytest.raises(ValueError,match='다른 작업'):reg.add('second')
    assert reg.usernames()==['first','pulled']


def test_account_http_api_roundtrip_and_conflict_error(tmp_path,monkeypatch):
    import json
    import threading
    from http.client import HTTPConnection
    from types import SimpleNamespace
    from hotpost import server
    settings=Settings(data_dir=tmp_path/'data',influencer_file=tmp_path/'accounts.txt')
    queue=SimpleNamespace(register=lambda *a:None,resume_queued=lambda:None)
    monkeypatch.setattr(server,'JobQueue',lambda *a:queue)
    for name in ('SourceJobManager','TranscriptJobManager','PlatformSessionManager',
                 'LegacyProductionManager','ProductionManager','Studio'):
        monkeypatch.setattr(server,name,lambda *a:SimpleNamespace())
    httpd=server.serve(settings,port=0)
    thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
    connection=HTTPConnection(*httpd.server_address,timeout=5)
    def request(method,path,body=None):
        connection.request(method,path,body=json.dumps(body) if body is not None else None,
                           headers={'Content-Type':'application/json'})
        response=connection.getresponse()
        return response.status,json.loads(response.read())
    try:
        code,body=request('POST','/api/accounts',{'account':'first','note':'개인 메모'})
        assert code==201 and body['created']
        assert load_usernames(settings.influencer_file)==['first']
        settings.influencer_file.write_text('@second\n@first\n',encoding='utf-8')
        code,body=request('GET','/api/accounts')
        assert code==200 and [a['username'] for a in body['accounts']]==['second','first']
        assert body['accounts'][1]['note']=='개인 메모'
        assert request('DELETE','/api/accounts/second')[0]==200
        assert load_usernames(settings.influencer_file)==['first']
        settings.influencer_file.write_text('<<<<<<< HEAD\n',encoding='utf-8')
        code,body=request('GET','/api/accounts')
        assert code==409 and '충돌' in body['error']
        assert db_names(AccountRegistry(settings))==['first']
    finally:
        connection.close();httpd.shutdown();httpd.server_close();thread.join(timeout=3)
