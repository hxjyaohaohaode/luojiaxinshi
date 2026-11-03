"""Bound the JVM directly; do not inherit the native Python parser's AS cap."""
import json
import sys

from .legacy_office import extract

if __name__=='__main__':
    try:
        if sys.platform!='win32':
            import resource
            resource.setrlimit(resource.RLIMIT_CPU,(18,18))
            resource.setrlimit(resource.RLIMIT_FSIZE,(4*1024*1024,4*1024*1024))
        result=extract(sys.stdin.buffer.read(5*1024*1024+1),sys.argv[1])
    except Exception as error:
        message=str(error)if isinstance(error,ValueError)else '旧格式文件损坏或无法可靠读取，请补充正文'
        result={'sections':[],'status':'failed','warning':message}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf-8'))
