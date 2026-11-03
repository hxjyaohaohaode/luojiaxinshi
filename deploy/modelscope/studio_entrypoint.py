"""Use the provider's runtime volume, then run the existing app as an unprivileged user."""
import os
from pathlib import Path

volume=Path('/mnt/workspace')
if not volume.is_dir():
    raise SystemExit('The runtime workspace volume is missing; refusing ephemeral account storage.')

# An OSSFS/FUSE workspace is not a verified SQLite WAL volume. In particular,
# directory existence and successful writes do not prove locking or mmap safety.
# Fail before creating data or touching credentials. This experimental target
# remains unavailable until the provider supplies a suitable persistent volume.
def persistent_sqlite_filesystem(path, mountinfo):
    import re
    choices=[]
    for line in mountinfo.splitlines():
        left,separator,right=line.partition(' - ')
        fields=left.split();types=right.split()
        if not separator or len(fields)<5 or not types:continue
        mount=Path(re.sub(r'\\([0-7]{3})',lambda m:chr(int(m.group(1),8)),fields[4]))
        if path.resolve().is_relative_to(mount):choices.append((len(mount.parts),types[0]))
    depth=max((item[0] for item in choices),default=0)
    # Multiple mounts at the same path must never let a lexicographically later
    # local filesystem conceal an object-store or network mount.
    return bool(choices) and all(kind in {'ext4','xfs','btrfs','zfs'} for level,kind in choices if level==depth)

if not persistent_sqlite_filesystem(volume,Path('/proc/self/mountinfo').read_text()):
    raise SystemExit('A verified persistent local SQLite volume is required; OSSFS, FUSE and ephemeral root filesystems are refused. Do not upload real accounts or keys to this experimental target.')
data=(volume/'luojiaxinshi-pilot').resolve()
if not data.is_relative_to(volume.resolve()):
    raise SystemExit('The application data directory is outside the runtime workspace.')
os.umask(0o077)
data.mkdir(mode=0o700,exist_ok=True)
if os.geteuid()==0:
    # Only the app's own directory, never other projects on a shared volume.
    for parent,dirs,files in os.walk(data,followlinks=False):
        for path in [Path(parent),*(Path(parent)/n for n in dirs+files)]:
            if path.is_symlink():raise SystemExit('Unexpected symlink in application data.')
            os.chown(path,10001,10001)
    os.setgroups([])
    os.setgid(10001)
    os.setuid(10001)
os.environ['APP_ENV']='production'
os.environ['APP_HOST']='0.0.0.0'
os.environ['APP_PORT']='7860'
os.environ['DATA_DIR']=str(data)
# The first deployment is locked until its actual platform URL is configured.
os.environ.setdefault('APP_ORIGIN','https://unconfigured.invalid')
os.execvp('python',['python','/app/manage.py','serve'])
