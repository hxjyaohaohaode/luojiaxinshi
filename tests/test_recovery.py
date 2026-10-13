import os
import sqlite3
import subprocess
import sys

import pytest

from app.config import ROOT
from app.backups import restore_database
from app.db import Database


def restore_cli(source, destination):
    return subprocess.run(
        [sys.executable, 'manage.py', 'restore', '--file', str(source)],
        cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
        env={**os.environ, 'PYTHONUTF8': '1', 'DATA_DIR': str(destination),
             'APP_ORIGIN': 'http://127.0.0.1:8765', 'APP_ENV': 'local'}, timeout=20)


@pytest.mark.parametrize('kind', ['unrelated', 'future', 'broken_relations'])
def test_rejected_restore_leaves_no_destination_database(tmp_path, kind):
    source=tmp_path/'backup.sqlite3'
    if kind=='unrelated':
        with sqlite3.connect(source) as conn:
            conn.execute('CREATE TABLE unrelated(value TEXT)')
    else:
        Database(source)
        with sqlite3.connect(source) as conn:
            if kind=='future':
                conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
            else:
                conn.execute("INSERT INTO sessions VALUES('invalid','missing-user','csrf',9999999999)")
    original=source.read_bytes()
    destination=tmp_path/'restored'
    result=restore_cli(source,destination)
    assert result.returncode!=0
    assert not (destination/'campus.sqlite3').exists()
    if destination.exists():
        assert not list(destination.glob('*.tmp'))
    assert source.read_bytes()==original


def test_existing_restore_target_is_never_overwritten(tmp_path):
    source=tmp_path/'backup.sqlite3'
    Database(source)
    destination=tmp_path/'existing'
    destination.mkdir()
    target=destination/'campus.sqlite3'
    target.write_bytes(b'Existing database must remain untouched')
    assert restore_cli(source,destination).returncode!=0
    assert target.read_bytes()==b'Existing database must remain untouched'


def test_opening_future_schema_does_not_add_tables(tmp_path):
    path=tmp_path/'future.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT)')
        conn.execute("INSERT INTO meta VALUES('schema_version','999')")
    with pytest.raises(RuntimeError):
        Database(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()==[('meta',)]


def test_restore_publish_failure_leaves_no_partial_file(tmp_path,monkeypatch):
    source=tmp_path/'backup.sqlite3'
    Database(source)
    destination=tmp_path/'restored'/'campus.sqlite3'
    def fail(*args):
        raise OSError('simulated filesystem failure')
    monkeypatch.setattr('app.backups.os.link',fail)
    with pytest.raises(OSError):
        restore_database(source,destination)
    assert not destination.exists()
    assert not list(destination.parent.iterdir())


def test_restore_publication_race_preserves_new_file(tmp_path,monkeypatch):
    source=tmp_path/'backup.sqlite3'
    Database(source)
    destination=tmp_path/'restored'/'campus.sqlite3'
    original_link=os.link
    def raced_link(staging,final):
        final.write_bytes(b'Created by another process')
        original_link(staging,final)
    monkeypatch.setattr('app.backups.os.link',raced_link)
    with pytest.raises(FileExistsError):
        restore_database(source,destination)
    assert destination.read_bytes()==b'Created by another process'
    assert list(destination.parent.iterdir())==[destination]
