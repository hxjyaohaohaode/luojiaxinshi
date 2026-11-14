"""FIFO admission for writers sharing one SQLite path in this process.

SQLite remains the lock authority across processes. Readers never enter this
queue, and queued time consumes the same acquisition budget as SQLite waiting.
Only live contenders retain a gate; historical database paths are not retained.
"""
from collections import deque
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from threading import Condition, Lock
import time
from weakref import WeakValueDictionary

WRITE_TIMEOUT_SECONDS = 15.0
_registry_guard = Lock()
_gates = WeakValueDictionary()


def _after_fork():
    # A child must not inherit a parent's in-progress thread ownership.
    global _registry_guard, _gates
    _registry_guard = Lock()
    _gates = WeakValueDictionary()


if hasattr(os, 'register_at_fork'):
    os.register_at_fork(after_in_child=_after_fork)


class _Gate:
    def __init__(self):
        self.changed = Condition()
        self.queue = deque()
        self.owner = None

    def acquire(self, token, deadline):
        with self.changed:
            self.queue.append(token)
            try:
                while True:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise sqlite3.OperationalError('database is locked: writer acquisition timed out')
                    if self.owner is None and self.queue[0] is token:
                        self.queue.popleft();self.owner = token
                        return
                    self.changed.wait(remaining)
            except BaseException:
                if self.owner is token:self.owner = None
                if token in self.queue:self.queue.remove(token)
                self.changed.notify_all()
                raise

    def release(self, token):
        with self.changed:
            if self.owner is token:self.owner = None
            elif token in self.queue:self.queue.remove(token)
            else:return
            self.changed.notify_all()


def _gate_for(path):
    key = os.path.normcase(str(Path(path).resolve()))
    with _registry_guard:
        gate = _gates.get(key)
        if gate is None:
            gate = _Gate();_gates[key] = gate
        return gate


class _Permit:
    def __init__(self, deadline):
        self.deadline = deadline

    def remaining(self):
        seconds = self.deadline-time.monotonic()
        if seconds <= 0:
            raise sqlite3.OperationalError('database is locked: writer acquisition timed out')
        return seconds


@contextmanager
def admission(path, timeout=None):
    deadline = time.monotonic()+(WRITE_TIMEOUT_SECONDS if timeout is None else timeout)
    gate = _gate_for(path);token = object()
    try:
        gate.acquire(token, deadline)
        yield _Permit(deadline)
    finally:
        gate.release(token)
