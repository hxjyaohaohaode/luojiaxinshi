"""Actual HTTP cache/compression and build provenance, not CSS snapshots."""
import json
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
from app.config import ROOT
from app.frontend_assets import built_index
from tests.test_workflow import env,account,ORIGIN


def test_checked_bundle_is_served_with_immutable_names_and_static_only_compression(env):
    app,_=env;c=TestClient(app,base_url=ORIGIN)
    manifest=json.loads((ROOT/'static/dist/manifest.json').read_text())
    assert app.state.frontend_bundled
    home=c.get('/')
    assert manifest['entries']['js'] in home.text and manifest['entries']['css'] in home.text
    assert home.headers['cache-control']=='no-store'
    js=c.get(manifest['entries']['js'],headers={'Accept-Encoding':'gzip'})
    assert js.status_code==200 and js.headers['content-encoding']=='gzip'
    assert 'immutable' in js.headers['cache-control'] and 'Accept-Encoding' in js.headers['vary']
    assert c.get('/api/health',headers={'Accept-Encoding':'gzip'}).headers.get('content-encoding') is None
    part=c.get(manifest['entries']['js'],headers={'Accept-Encoding':'gzip','Range':'bytes=0-49'})
    assert part.status_code==206 and part.headers.get('content-encoding') is None and len(part.content)==50
    source=c.get('/static/app.js',headers={'Accept-Encoding':'identity'})
    assert source.headers['cache-control']=='no-cache'
    assert c.get('/static/app.js',headers={'If-None-Match':source.headers['etag']}).status_code==304


def test_build_verification_falls_back_for_changed_source_or_missing_output(tmp_path):
    # A small real manifest exercises both halves of provenance without copying
    # the entire repository or modifying shared source files during parallel tests.
    import hashlib
    folder=tmp_path/'static';dist=folder/'dist';dist.mkdir(parents=True)
    (folder/'app.js').write_text('export const value=1;')
    (dist/'index.html').write_text('built')
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    value={'format':1,'sources':{'static/app.js':digest(folder/'app.js')},'outputs':{'static/dist/index.html':digest(dist/'index.html')}}
    (dist/'manifest.json').write_text(json.dumps(value))
    assert built_index(tmp_path)==dist/'index.html'
    (folder/'app.js').write_text('export const value=2;')
    assert built_index(tmp_path) is None
    (folder/'app.js').write_text('export const value=1;');(dist/'index.html').unlink()
    assert built_index(tmp_path) is None
