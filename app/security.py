import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password):
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return salt.hex() + ":" + value.hex()


def verify_password(password, stored):
    try:
        salt, expected = stored.split(":")
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


DUMMY_PASSWORD = hash_password(secrets.token_urlsafe(24))


def rate_limit(db, key, maximum, seconds):
    now = int(time.time())
    with db.connect(write=True) as conn:
        conn.execute("DELETE FROM limits WHERE reset_at < ?", (now,))
        row = conn.execute("SELECT * FROM limits WHERE key=?", (key,)).fetchone()
        if row and row['count'] >= maximum:
            raise HTTPException(429, "操作过于频繁，请稍后再试", headers={"Retry-After": str(max(1, row['reset_at']-now))})
        conn.execute("INSERT INTO limits VALUES(?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1", (key, now+seconds))


def new_invite(db, role='user'):
    raw = secrets.token_urlsafe(32)
    now = int(time.time())
    with db.connect(write=True) as conn:
        conn.execute("INSERT INTO invites VALUES(?,?,?,NULL,?)", (token_hash(raw), role, now+7*86400, now))
    return raw
