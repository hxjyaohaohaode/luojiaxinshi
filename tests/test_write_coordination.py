"""Real SQLite contention, FIFO admission and resource-release fault paths."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import local
import time

import pytest

from app import db as database_module, runtime_metrics
from app import write_coordination as coordination
from app.db import Database


@pytest.fixture
def database(tmp_path):
    result=Database(tmp_path/'shared.sqlite3')
    with result.connect(write=True) as conn:
        conn.execute('CREATE TABLE write_probe(value TEXT NOT NULL)')
    return result


def queued(gate, count):
    until=time.monotonic()+4
    while time.monotonic()<until:
        with gate.changed:
            if len(gate.queue)==count:return
        time.sleep(.002)
    raise AssertionError('writers did not reach the admission queue')


def insert(database, value):
    with database.connect(write=True) as conn:
        conn.execute('INSERT INTO write_probe VALUES(?)',(value,))


def values(database):
    with database.connect() as conn:
        return [row[0] for row in conn.execute('SELECT value FROM write_probe ORDER BY rowid')]


def test_actual_writers_are_fifo_across_database_instances_and_reads_stay_parallel(database,tmp_path):
    (tmp_path/'alias').mkdir()
    second=Database(tmp_path/'alias'/'..'/'shared.sqlite3')
    gate=coordination._gate_for(database.path)
    with ThreadPoolExecutor(max_workers=5) as pool:
        with database.connect(write=True) as held:
            held.execute("INSERT INTO write_probe VALUES('held')")
            assert pool.submit(values,second).result(timeout=4)==[]
            workers=[]
            for index in range(4):
                workers.append(pool.submit(insert,second if index%2 else database,str(index)))
                queued(gate,index+1)
        for worker in workers:worker.result(timeout=4)
    assert values(database)==['held','0','1','2','3']
    assert gate.owner is None and not gate.queue


@pytest.mark.parametrize('error',[ValueError,asyncio.CancelledError])
def test_body_failure_and_cancellation_roll_back_close_and_release(database,error):
    gate=coordination._gate_for(database.path)
    with pytest.raises(error):
        with database.connect(write=True) as conn:
            conn.execute("INSERT INTO write_probe VALUES('aborted')")
            raise error('synthetic interrupted transaction')
    with pytest.raises(sqlite3.ProgrammingError):conn.execute('SELECT 1')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(insert,database,'following').result(timeout=4)
    assert values(database)==['following'] and gate.owner is None and not gate.queue


def test_real_connection_open_failure_does_not_keep_the_admission(database):
    gate=coordination._gate_for(database.path)
    saved=database.path.with_suffix('.saved')
    database.path.rename(saved);database.path.mkdir()
    try:
        with pytest.raises(sqlite3.OperationalError):
            with database.connect(write=True):pytest.fail('a directory cannot be a SQLite database')
    finally:
        database.path.rmdir();saved.rename(database.path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(insert,database,'recovered').result(timeout=4)
    assert values(database)==['recovered'] and gate.owner is None and not gate.queue


def test_queue_and_external_sqlite_contention_share_budget_and_both_appear_in_wait_metrics(database,monkeypatch):
    # This raw connection intentionally represents a writer outside the local
    # admission queue. SQLite must remain the final cross-process constraint.
    raw=sqlite3.connect(database.path,isolation_level=None)
    raw.execute('BEGIN IMMEDIATE')
    monkeypatch.setattr(coordination,'WRITE_TIMEOUT_SECONDS',.6)
    budgets=[];observed=[];original_record=runtime_metrics.record
    class Measured(database_module.CapacityConnection):
        def execute(self, sql, *args, **kwargs):
            if sql=='BEGIN IMMEDIATE':
                budgets.append(super().execute('PRAGMA busy_timeout').fetchone()[0])
            return super().execute(sql,*args,**kwargs)
    def record(path,kind,milliseconds,failed=False):
        observed.append((kind,milliseconds,failed))
        original_record(path,kind,milliseconds,failed)
    monkeypatch.setattr(database_module,'CapacityConnection',Measured)
    monkeypatch.setattr(runtime_metrics,'record',record)
    gate=coordination._gate_for(database.path)
    def contend():
        started=time.perf_counter()
        with pytest.raises(sqlite3.OperationalError,match='locked'):
            insert(database,'must not commit')
        return time.perf_counter()-started
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with coordination.admission(database.path,timeout=2):
                pending=pool.submit(contend);queued(gate,1)
                time.sleep(.35)
            elapsed=pending.result(timeout=3)
        assert budgets and 0<=budgets[0]<280
        assert .55<=elapsed<1.1
        waits=[ms for kind,ms,failed in observed if kind=='wait' and failed]
        assert len(waits)==1 and waits[0]>=550
        assert abs(waits[0]-elapsed*1000)<40
    finally:
        raw.rollback();raw.close()
    insert(database,'after external release')
    assert values(database)==['after external release']
    assert gate.owner is None and not gate.queue


def test_cancelled_queued_writer_cannot_block_the_next_real_transaction(database,monkeypatch):
    gate=coordination._gate_for(database.path);thread=local();original_wait=gate.changed.wait
    def wait(timeout=None):
        if getattr(thread,'cancel',False):raise asyncio.CancelledError('synthetic queue cancellation')
        return original_wait(timeout)
    monkeypatch.setattr(gate.changed,'wait',wait)
    def writer(cancel,value):
        thread.cancel=cancel
        insert(database,value)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with database.connect(write=True):
            cancelled=pool.submit(writer,True,'cancelled')
            with pytest.raises(asyncio.CancelledError):cancelled.result(timeout=4)
            follower=pool.submit(writer,False,'survivor');queued(gate,1)
        follower.result(timeout=4)
    assert values(database)==['survivor'] and gate.owner is None and not gate.queue


def test_timed_out_queue_head_is_removed_and_a_later_writer_can_commit(database,monkeypatch):
    gate=coordination._gate_for(database.path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with database.connect(write=True):
            with monkeypatch.context() as patch:
                patch.setattr(coordination,'WRITE_TIMEOUT_SECONDS',.2)
                expired=pool.submit(insert,database,'timed out');queued(gate,1)
            survivor=pool.submit(insert,database,'still queued')
            with pytest.raises(sqlite3.OperationalError,match='timed out'):expired.result(timeout=4)
            queued(gate,1)
        survivor.result(timeout=4)
    assert values(database)==['still queued'] and gate.owner is None and not gate.queue


@pytest.mark.parametrize('failure',['commit','rollback','close'])
def test_sqlite_cleanup_failures_still_release_the_path_for_the_next_writer(database,monkeypatch,failure):
    gate=coordination._gate_for(database.path)
    class Broken(database_module.CapacityConnection):
        def commit(self):
            if failure=='commit':raise sqlite3.OperationalError('synthetic commit failure')
            return super().commit()
        def rollback(self):
            if failure=='rollback':raise sqlite3.OperationalError('synthetic rollback failure')
            return super().rollback()
        def close(self):
            super().close()
            if failure=='close':raise sqlite3.OperationalError('synthetic close failure')
    with monkeypatch.context() as patch:
        patch.setattr(database_module,'CapacityConnection',Broken)
        with pytest.raises(sqlite3.OperationalError,match='synthetic '+failure):
            with database.connect(write=True) as conn:
                conn.execute('INSERT INTO write_probe VALUES(?)',(failure,))
                if failure=='rollback':raise ValueError('trigger rollback')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(insert,database,'next').result(timeout=4)
    assert values(database)==(['close','next'] if failure=='close' else ['next'])
    assert gate.owner is None and not gate.queue
