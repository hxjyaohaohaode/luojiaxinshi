"""Per-thread files plus an opt-in Docker process sandbox. Never run host shell code."""
import asyncio
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid

from .types import AgentError

MAX_BYTES = 128000


def linked(path):
    if not path.exists() and not path.is_symlink():
        return False
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


class Files:
    def __init__(self, base, uid, tid):
        if not re.fullmatch(r'[0-9a-f]{32}', uid) or not re.fullmatch(r'[0-9a-f]{32}', tid):
            raise AgentError('工作区标识无效')
        self.base = Path(base).absolute()
        self.root = self.base / 'agent-workspaces' / uid / tid
        self.check_parents(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def check_parents(self, path):
        # Includes the configured data directory and all ancestors, including
        # Windows junctions. This is not a defence against a malicious host admin.
        for candidate in [path, *path.parents]:
            if linked(candidate):
                raise AgentError('工作区不能经过符号链接或目录联接')

    def path(self, name):
        if '\\' in name or ':' in name or '\x00' in name:
            raise AgentError('只接受工作区内的相对路径')
        parts = PurePosixPath(name).parts
        if not parts or name.startswith('/') or any(p in {'.', '..'} or p.startswith('.') or p.endswith((' ', '.')) or re.match(r'^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)', p, re.I) for p in parts):
            raise AgentError('路径越界或使用了保留名称')
        target = self.root.joinpath(*parts)
        self.check_parents(target)
        if not target.resolve().is_relative_to(self.root.resolve()):
            raise AgentError('路径越出工作区')
        if target.exists() and (not target.is_file() or target.stat().st_nlink > 1):
            raise AgentError('只能访问普通且无硬链接的文件')
        return target

    def read(self, name):
        path = self.path(name)
        try:
            with path.open('rb') as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise AgentError('文件超过读取上限')
            return {'path': name, 'content': raw.decode('utf-8'), 'sha256': hashlib.sha256(raw).hexdigest()}
        except (OSError, UnicodeError):
            raise AgentError('文件不存在、不可读取或不是 UTF-8 文本') from None

    def write(self, name, content, expected):
        path = self.path(name)
        if path.exists():
            current = self.read(name)['sha256']
            if not expected or current != expected:
                raise AgentError('文件已存在或发生变更，请先读取并使用当前 SHA256')
        elif expected:
            raise AgentError('预期文件已不存在，请重新核对')
        raw = content.encode('utf-8')
        if len(raw) > MAX_BYTES:
            raise AgentError('文件超过写入上限')
        items = list(self.root.rglob('*'))
        if len(items) >= 200 or sum(p.lstat().st_size for p in items if p.is_file() and not linked(p)) + len(raw) > 10 * 1048576:
            raise AgentError('工作区达到 200 项或 10 MB 配额')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.check_parents(path.parent)
        fd, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw)
            # Recheck immediately before the atomic replacement.
            self.path(name)
            if path.exists() and self.read(name)['sha256'] != expected:
                raise AgentError('保存前文件已变化')
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

    def listing(self):
        result = []
        for path in self.root.rglob('*'):
            if len(result) >= 200:
                break
            name = path.relative_to(self.root).as_posix()
            if path.is_file():
                self.path(name)
                result.append({'path': name, 'bytes': path.stat().st_size})
        return result


async def command(files, argv, image):
    if not image or not re.fullmatch(r'[A-Za-z0-9._/:@-]+@sha256:[a-f0-9]{64}', image):
        raise AgentError('命令沙箱未配置：维护者须设置带 SHA256 摘要的 AGENT_SANDBOX_IMAGE')
    docker = shutil.which('docker')
    if not docker:
        raise AgentError('Docker 沙箱不可用，已拒绝执行命令')
    if any(not arg or len(arg) > 4000 or '\x00' in arg for arg in argv):
        raise AgentError('命令参数无效')
    files.check_parents(files.root)
    # No host directory is writable by the container. Artifacts are produced
    # through the separate, hash-checked write_file tool after owner approval.
    name = 'campus-agent-' + uuid.uuid4().hex
    if ',' in str(files.root):
        raise AgentError('Docker 工作区路径不能含逗号')
    args = [docker, 'run', '--rm', '--pull=never', '--name', name, '--network=none', '--read-only',
            '--cap-drop=ALL', '--security-opt=no-new-privileges', '--pids-limit=64', '--memory=256m', '--cpus=1',
            '--user=65534:65534', '--tmpfs=/tmp:rw,noexec,nosuid,size=16m', '--workdir=/workspace',
            '--mount', f'type=bind,source={files.root},target=/workspace,readonly', '--entrypoint', argv[0], image, *argv[1:]]
    options = {'creationflags': 0x08000000} if os.name == 'nt' else {}
    try:
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **options)
    except OSError:
        raise AgentError('Docker 沙箱无法启动') from None
    complete = False
    try:
        async with asyncio.timeout(30):
            chunks = bytearray()
            while chunk := await process.stdout.read(4096):
                chunks.extend(chunk)
                if len(chunks) > 32000:
                    raise AgentError('命令输出超过 32 KB，已停止沙箱')
            code = await process.wait()
        complete = True
        return {'exit_code': code, 'output': chunks.decode('utf-8', errors='replace')}
    except TimeoutError:
        raise AgentError('命令超过 30 秒，已停止沙箱') from None
    finally:
        if not complete:
            # Killing the Docker client does not stop its container; remove by
            # the generated name as well, including during cancellation.
            if process.returncode is None:
                process.kill()
            await process.wait()
            try:
                cleanup = await asyncio.create_subprocess_exec(docker, 'rm', '-f', name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, **options)
                await asyncio.wait_for(cleanup.wait(), 10)
            except (OSError, TimeoutError):
                pass
