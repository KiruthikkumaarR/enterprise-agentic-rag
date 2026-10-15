"""SQLite storage for the portal: users, sessions, documents (with access metadata), query log, activity log."""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

from .company_data import ACCOUNTS, MANIFEST, PORTAL_DIR

DB_PATH = PORTAL_DIR / "portal.db"
SESSION_TTL = 8 * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  username TEXT PRIMARY KEY, full_name TEXT, title TEXT, department TEXT, role TEXT,
  pw_salt BLOB, pw_hash BLOB, active INTEGER DEFAULT 1, created REAL, last_login REAL);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, username TEXT, created REAL, expires REAL);
CREATE TABLE IF NOT EXISTS documents (
  doc TEXT PRIMARY KEY, title TEXT, departments TEXT, level INTEGER, owner TEXT, created TEXT,
  description TEXT, category TEXT, source TEXT, uploaded_by TEXT, chunks INTEGER DEFAULT 0, size_bytes INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS queries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, username TEXT, question TEXT, status TEXT, answer TEXT,
  citations TEXT, retrieved TEXT, latency REAL);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, username TEXT, action TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS login_attempts (username TEXT, ts REAL, ok INTEGER);
CREATE TABLE IF NOT EXISTS user_widgets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, spec TEXT, created REAL);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


# --------------------------------------------------------------------------- passwords
def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or os.urandom(16)
    return salt, hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    return hmac.compare_digest(hash_password(password, salt)[1], expected)


# --------------------------------------------------------------------------- setup
def init(seed_users: bool = True, seed_docs: bool = True):
    PORTAL_DIR.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)
        if seed_users and not c.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            with open(ACCOUNTS) as f:
                for r in csv.DictReader(f):
                    salt, h = hash_password(r["password"])
                    c.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?,1,?,NULL)",
                              (r["username"], r["full_name"], r["title"], r["department"], r["role"], salt, h, time.time()))
        if seed_docs and not c.execute("SELECT 1 FROM documents LIMIT 1").fetchone():
            for d in json.loads(MANIFEST.read_text()):
                upsert_document(c, d)


def upsert_document(c, d: dict):
    c.execute("INSERT OR REPLACE INTO documents (doc,title,departments,level,owner,created,description,category,source,uploaded_by,chunks,size_bytes) "
              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (d["doc"], d["title"], json.dumps(d["departments"]), int(d["level"]), d["owner"], d["created"], d.get("description", ""),
               d.get("category", ""), d.get("source", "generated"), d.get("uploaded_by"), d.get("chunks", 0), d.get("size_bytes", 0)))


def doc_row(r) -> dict:
    d = dict(r)
    d["departments"] = json.loads(d["departments"])
    return d


# --------------------------------------------------------------------------- sessions
def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with conn() as c:
        c.execute("DELETE FROM sessions WHERE expires < ?", (now,))
        c.execute("INSERT INTO sessions VALUES (?,?,?,?)", (_h(token), username, now, now + SESSION_TTL))
        c.execute("UPDATE users SET last_login=? WHERE username=?", (now, username))
    return token


def session_user(token: str | None) -> dict | None:
    if not token:
        return None
    with conn() as c:
        r = c.execute("SELECT u.* FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=? AND s.expires>? AND u.active=1",
                      (_h(token), time.time())).fetchone()
    if not r:
        return None
    u = dict(r)
    u.pop("pw_salt"); u.pop("pw_hash")
    return u


def drop_session(token: str | None):
    if token:
        with conn() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (_h(token),))


def recent_failures(username: str, window: float = 300) -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM login_attempts WHERE username=? AND ok=0 AND ts>?",
                         (username, time.time() - window)).fetchone()[0]


def log_attempt(username: str, ok: bool):
    with conn() as c:
        c.execute("INSERT INTO login_attempts VALUES (?,?,?)", (username, time.time(), int(ok)))


def log_activity(username: str, action: str, detail: str = ""):
    with conn() as c:
        c.execute("INSERT INTO activity (ts,username,action,detail) VALUES (?,?,?,?)", (time.time(), username, action, detail))
