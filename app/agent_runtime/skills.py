"""Metadata-first discovery of administrator-installed, declarative SKILL.md files."""
from pathlib import Path
import re

from .sandbox import linked
from .types import AgentError


class Skills:
    def __init__(self, root):
        self.root = Path(root)

    def catalog(self):
        if not self.root.exists():
            return []
        if any(linked(p) for p in [self.root, *self.root.parents]):
            raise AgentError('技能目录不能经过链接')
        result = []
        for path in sorted(self.root.glob('*/SKILL.md'))[:50]:
            if linked(path.parent) or linked(path) or path.stat().st_size > 24000:
                continue
            raw = path.read_text(encoding='utf-8')
            if not raw.startswith('---\n') or '\n---\n' not in raw[4:]:
                continue
            front, body = raw[4:].split('\n---\n', 1)
            fields = {}
            for line in front.splitlines():
                key, sep, value = line.partition(':')
                if sep:
                    fields[key.strip()] = value.strip().strip('"\'')
            name, description = fields.get('name', ''), fields.get('description', '')
            if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', name) or name != path.parent.name or not description or len(description) > 500:
                continue
            result.append({'name': name, 'description': description, 'body': body})
        return result

    def metadata(self):
        return [{k: item[k] for k in ('name', 'description')} for item in self.catalog()]

    def load(self, name):
        for item in self.catalog():
            if item['name'] == name:
                return item['body']
        raise AgentError('技能不存在或元数据不符合格式')
