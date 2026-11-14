"""Serve a verified prebuilt frontend; source edits retain the development path."""
import hashlib
import json
import logging
from pathlib import Path

from starlette.middleware.gzip import GZipMiddleware


def built_index(root:Path):
    manifest=root/'static/dist/manifest.json'
    if not manifest.is_file():return None
    try:
        value=json.loads(manifest.read_text(encoding='utf8'))
        if value.get('format')!=1:raise ValueError('unsupported_manifest')
        for name,digest in {**value['sources'],**value['outputs']}.items():
            path=(root/name).resolve()
            if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
                raise ValueError('stale_asset')
        return root/'static/dist/index.html'
    except (ValueError,KeyError,TypeError,OSError):
        logging.getLogger('campus').warning('frontend_build_stale_using_sources')
        return None


class StaticCompression:
    """Compress public static files only; API/SSE/private responses are untouched."""
    def __init__(self,app):
        self.app=app
        self.compressed=GZipMiddleware(app,minimum_size=800,compresslevel=6)

    async def __call__(self,scope,receive,send):
        path=scope.get('path','')
        ranged=any(key.lower()==b'range' for key,_ in scope.get('headers',[]))
        compress=scope['type']=='http' and path.startswith('/static/') and path.endswith(('.js','.css','.html','.json','.svg','.webmanifest')) and not ranged
        target=self.compressed if compress else self.app
        await target(scope,receive,send)
