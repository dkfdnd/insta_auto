import sqlite3
from types import SimpleNamespace
from hotpost.reference_context import post_caption, reference_kind
import json


def test_caption_read_is_source_specific_and_preserves_database(tmp_path):
    path=tmp_path/'posts.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE posts (shortcode TEXT, caption TEXT)')
        db.execute('INSERT INTO posts VALUES (?,?)',('one','댓글에 투두 남겨주세요'))
    before=path.read_bytes()
    settings=SimpleNamespace(db_path=path)
    assert post_caption(settings,{'shortcode':'one'})=='댓글에 투두 남겨주세요'
    assert post_caption(settings,{'shortcode':'missing'})==''
    assert path.read_bytes()==before


def test_missing_db_is_not_created_and_saved_caption_is_preserved(tmp_path):
    path=tmp_path/'absent.sqlite';settings=SimpleNamespace(db_path=path)
    assert post_caption(settings,{'shortcode':'one'})==''
    assert not path.exists()
    assert post_caption(settings,{'original_caption':'원본 본문'})=='원본 본문'


def test_source_kind_is_based_on_actual_saved_evidence(tmp_path):
    path=tmp_path/'transcript.json'
    path.write_text(json.dumps({'speech':[{'text':'원본 발화'}], 'screen_text':[{'text':'화면 글자'}]},ensure_ascii=False),'utf-8')
    state={'original_text':'원본 발화','transcript_path':str(path)}
    assert reference_kind(state)=='speech'
    assert reference_kind({**state,'original_text':'화면 글자'})=='screen_text'
    assert reference_kind({**state,'reviewed_original_text':'교정한 문장'})=='provided_text'
    assert reference_kind({**state,'reference_kind':'mixed'})=='mixed'
    assert reference_kind({'original_text':'저장된 글'})=='provided_text'
