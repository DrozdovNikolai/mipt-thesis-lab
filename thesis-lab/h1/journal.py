"""Durable protocol driver storage; this is not a replacement for Flutter storage."""
import hashlib
import json
import sqlite3

def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)

def connect(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    return db

def create(path, fixture):
    if path.exists():
        raise FileExistsError(path)
    db = connect(path)
    with db:
        db.executescript('''
        CREATE TABLE intent(id INTEGER PRIMARY KEY CHECK(id=1), expected TEXT NOT NULL,
                            submit_body TEXT NOT NULL, sha256 TEXT NOT NULL);
        CREATE TRIGGER intent_no_update BEFORE UPDATE ON intent BEGIN SELECT RAISE(ABORT,'immutable intent'); END;
        CREATE TRIGGER intent_no_delete BEFORE DELETE ON intent BEGIN SELECT RAISE(ABORT,'immutable intent'); END;
        CREATE TABLE queue(id INTEGER PRIMARY KEY, path TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL);
        CREATE TRIGGER queue_no_update BEFORE UPDATE ON queue BEGIN SELECT RAISE(ABORT,'immutable delivery'); END;
        CREATE TABLE receipt(id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL, accepted_at REAL NOT NULL);
        ''')
        submit = encode(fixture['queue'][-1]['body'])
        db.execute('INSERT INTO intent VALUES(1,?,?,?)', (encode(fixture['expected']),submit,hashlib.sha256(submit.encode()).hexdigest()))
        db.executemany('INSERT INTO queue VALUES(?,?,?,?)',
            [(i,item['path'],encode(item['body']),hashlib.sha256(encode(item['body']).encode()).hexdigest())
             for i,item in enumerate(fixture['queue'])])
    db.close()

def receipt_matches(response, expected):
    r = response.get('submitReceipt') or {}
    return (response.get('trainingId') == expected['training_id']
        and response.get('trainingStatus') == 'COMPLETED'
        and response.get('assessmentsCompleted') is True
        and bool(response.get('submittedAt'))
        and r.get('version') == 1 and r.get('trainingId') == expected['training_id']
        and r.get('submissionManifestHash') == expected['manifest']
        and r.get('writerInstanceId') == expected['writer'] and r.get('writerEpoch') == 1
        and r.get('currentEventId') == expected['last_event']
        and r.get('acceptedThroughClientSequence') == expected['steps']
        and r.get('serverRevision') == expected['steps'] and r.get('sealed') is True)
