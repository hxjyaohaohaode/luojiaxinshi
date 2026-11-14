"""Observe real contention without exposing database paths or owner data."""
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from app.db import Database
from app.runtime_metrics import summary


def test_sqlite_wait_and_hold_are_distinct_bounded_redacted_observations(tmp_path):
    db=Database(tmp_path/'private-name.sqlite3');entered=threading.Event();release=threading.Event()
    def hold():
        with db.connect(write=True):
            entered.set();assert release.wait(5)
    def writer():
        with db.connect(write=True) as conn:conn.execute("INSERT INTO meta VALUES('measured_fixture','1')")
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(hold);assert entered.wait(5)
        waiting=pool.submit(writer)
        time.sleep(.05);release.set()
        first.result(timeout=5);waiting.result(timeout=5)
    data=summary(db.path)
    assert data['observed'] and data['failed_acquisitions']==0
    assert data['wait']['samples']>=2 and data['hold']['samples']>=2
    assert data['wait']['max_ms']>=10 and data['hold']['max_ms']>=40
    assert 'private-name' not in str(data) and str(tmp_path) not in str(data)
    assert not summary(tmp_path/'different.sqlite3')['observed']
