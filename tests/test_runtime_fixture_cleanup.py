from types import SimpleNamespace

import pytest

from scripts.verify_local_runtime import cleanup_fixture


def locked():
    error=PermissionError('simulated inherited Windows handle')
    error.winerror=32
    return error


def test_fixture_cleanup_retries_a_transient_windows_handle(tmp_path,monkeypatch):
    attempts=[];waits=[]
    def cleanup():
        attempts.append(1)
        if len(attempts)<3:raise locked()
    monkeypatch.setattr('scripts.verify_local_runtime.time.sleep',waits.append)
    cleanup_fixture(SimpleNamespace(name=str(tmp_path/'runtime-check-owned'),cleanup=cleanup),tmp_path)
    assert len(attempts)==3 and waits==[.1,.2]


def test_fixture_cleanup_keeps_permanent_errors_visible(tmp_path,monkeypatch):
    attempts=[]
    def cleanup():
        attempts.append(1)
        raise locked()
    monkeypatch.setattr('scripts.verify_local_runtime.time.sleep',lambda _:None)
    with pytest.raises(PermissionError):
        cleanup_fixture(SimpleNamespace(name=str(tmp_path/'runtime-check-owned'),cleanup=cleanup),tmp_path)
    assert len(attempts)==12


def test_fixture_cleanup_never_removes_an_unowned_path(tmp_path):
    def unexpected():raise AssertionError('cleanup must not run')
    with pytest.raises(RuntimeError,match='Refusing cleanup'):
        cleanup_fixture(SimpleNamespace(name=str(tmp_path/'unrelated'),cleanup=unexpected),tmp_path)
    with pytest.raises(RuntimeError,match='Refusing cleanup'):
        cleanup_fixture(SimpleNamespace(name=str(tmp_path.parent/'runtime-check-outside'),cleanup=unexpected),tmp_path)
