import json
import sys
import time

import pytest

from hotpost.writing import codex_writer


@pytest.mark.skipif(codex_writer.os.name != 'nt', reason='Windows desktop installation')
def test_scheduled_task_resolves_installed_cli_without_desktop_path(tmp_path, monkeypatch):
    binary = tmp_path/'OpenAI'/'Codex'/'bin'/'installed-version'/'codex.exe'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fixture')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(codex_writer.shutil, 'which', lambda name:None)
    assert codex_writer.executable() == str(binary)


def test_missing_cli_still_fails_instead_of_using_another_model(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setattr(codex_writer.shutil, 'which', lambda name:None)
    with pytest.raises(RuntimeError, match='CLI'):
        codex_writer.executable()

def test_cli_command_is_text_only_and_uses_existing_auth():
    args = codex_writer.command('codex', 'cwd', 'schema', 'output')
    assert '--ignore-user-config' in args and '--ephemeral' in args
    assert args[args.index('--sandbox')+1] == 'read-only'
    assert 'shell_tool' in args and 'web_search="disabled"' in args
    assert '-m' not in args and not any('token' in arg.lower() for arg in args)


def test_inner_schema_is_validated():
    schema = {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}
    assert codex_writer.decode(json.dumps({'text': '{"text":"ok"}'}), schema) == {'text': 'ok'}
    with pytest.raises(ValueError, match='형식'):
        codex_writer.decode(json.dumps({'text': '{"text":1}'}), schema)


def test_timeout_terminates_only_spawned_child_and_records_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_writer, 'executable', lambda: sys.executable)
    monkeypatch.setattr(codex_writer, 'command', lambda *a: [sys.executable, '-c', 'import time;time.sleep(30)'])
    state = {'directory': tmp_path, 'calls': []}
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        codex_writer.chat('rules', 'data', None, lambda: None, state, timeout=.1)
    assert time.monotonic()-start < 10
    assert state['calls'][0]['status'] == 'failed'
    import psutil
    assert not psutil.pid_exists(state['calls'][0]['pid'])
