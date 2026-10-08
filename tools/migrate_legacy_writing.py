"""Explicit one-time, read-only import of finished script service job records."""
import argparse
import json
import sqlite3
from pathlib import Path


def migrate(database, destination):
    database=Path(database).resolve(strict=True)
    destination=Path(destination).resolve()
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        db.execute('BEGIN')
        if db.execute("SELECT 1 FROM jobs WHERE state IN ('running','queued')").fetchone():
            raise RuntimeError('기존 집필 작업이 진행 중입니다. 완료 후 이전하세요.')
        rows=db.execute('SELECT id,kind,title,state,progress,message,payload,result,error,created,updated,cancel FROM jobs').fetchall()
    destination.mkdir(parents=True,exist_ok=True)
    for row in rows:
        value=dict(row)
        if not value['id'].isalnum():raise ValueError('잘못된 기존 작업 ID')
        for key in ('payload','result'):value[key]=json.loads(value[key]) if value[key] else None
        target=destination/(value['id']+'.json')
        if target.exists():
            if json.loads(target.read_text('utf-8'))!=value:
                raise ValueError('다른 내용의 기존 보관 기록을 덮어쓰지 않았습니다: '+value['id'])
            continue
        temporary=target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value,ensure_ascii=False),'utf-8');temporary.replace(target)
    return len(rows)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--destination',required=True,type=Path)
    args=parser.parse_args()
    print('Archived records:',migrate(args.database,args.destination))
