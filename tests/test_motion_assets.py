"""A clean checkout must reproduce the vectors shipped by the application."""
import importlib.util
from pathlib import Path


def test_motion_assets_rebuild_from_repository_sources(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('motion_builder', root / 'scripts/build_motion_assets.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    (tmp_path / 'static/assets').mkdir(parents=True)
    builder.build({
        'legacy': root / 'design/motion/SVG矢量图与动效全集.html',
        'v2': root / 'design/motion/SVG矢量图与动效系统_v2.html',
    })
    for name in ('static/motion-assets.js', 'static/motion-source.css', 'static/assets/motion-provenance.json'):
        assert (tmp_path / name).read_text(encoding='utf-8') == (root / name).read_text(encoding='utf-8'), name
