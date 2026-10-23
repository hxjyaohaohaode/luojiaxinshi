from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'scripts'))
import run_browser_checks


def test_browser_suite_limit_reset_is_confined_to_the_owned_synthetic_database(tmp_path,monkeypatch):
    monkeypatch.setattr(run_browser_checks,'ROOT',tmp_path)
    monkeypatch.setattr(run_browser_checks,'OUT',tmp_path/'artifacts/ci-browser')
    data=tmp_path/'artifacts/ci-browser/fixture-test';data.mkdir(parents=True)
    with sqlite3.connect(data/'campus.sqlite3') as connection:
        connection.execute('CREATE TABLE limits (key TEXT)')
        connection.execute("INSERT INTO limits VALUES ('synthetic-login')")
    with pytest.raises(ValueError,match='owned synthetic'):
        run_browser_checks.reset_fixture_limits(tmp_path/'data')
    run_browser_checks.reset_fixture_limits(data)
    with sqlite3.connect(data/'campus.sqlite3') as connection:
        assert connection.execute('SELECT COUNT(*) FROM limits').fetchone()[0]==0
