"""Quiet startup probe, in a file to avoid Windows shell argument quoting."""
from importlib.util import find_spec
import sys

modules=('fastapi','uvicorn','httpx','pypdf','icalendar','defusedxml','dotenv','python_multipart','PIL','cryptography','pywebpush')
sys.exit(0 if all(find_spec(name) for name in modules) else 1)
