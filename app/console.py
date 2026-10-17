"""Consistent UTF-8 command output, including Windows redirected byte pipes."""
import sys


def configure_text_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if callable(reconfigure):
            reconfigure(encoding='utf-8', errors='backslashreplace')
