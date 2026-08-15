"""Atomic, cross-worker run locks backed by Redis (via frappe.cache()).

Acquire uses `SET key token NX EX ttl` — atomic, and self-healing when a worker
dies (the TTL expires, so a crashed job can never wedge a page/session forever).
The returned token FENCES release: a worker that outlived its TTL can no longer
delete the lock a newer holder acquired (release compares the token in Redis).

`frappe.cache()` is a `redis.Redis` subclass, so the raw `.set(nx=, ex=)` is used
directly for atomicity (the `set_value` helper has no NX flag). `make_key` scopes
every lock to the current site.
"""

import secrets
from contextlib import contextmanager

import frappe

# TTLs sit just above the turn job's timeout (600s) so a dead worker's lock
# expires on its own.
PAGE_LOCK_TTL = 660
SESSION_LOCK_TTL = 660

RELEASE_IF_TOKEN_MATCHES = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""


def page_key(page_id: str) -> str:
	"""One writer per page: an app-wide turn touching several pages takes each
	page's lock while it edits that page."""
	return f"studio_ai_page_lock:{page_id}"


def session_key(session_id: str) -> str:
	"""One running turn per chat session (replaces the old is_running DB flag,
	which was a non-atomic check-then-set and needed manual repair after a crash)."""
	return f"studio_ai_session_lock:{session_id}"


def acquire(key: str, ttl: int) -> str | None:
	"""Atomically acquire `key`. Returns the release token, or None if already held."""
	token = secrets.token_hex(8)
	# make_key scopes the key to the current site, so this is multi-tenant safe; the
	# raw client is required because set_value has no NX flag (see module docstring).
	cache = frappe.cache()  # nosemgrep
	return token if cache.set(cache.make_key(key), token, nx=True, ex=ttl) else None


def release(key: str, token: str | None) -> None:
	"""Release `key` only if we still hold it (token match) — never a newer holder's lock."""
	if not token:
		return
	cache = frappe.cache()
	cache.eval(RELEASE_IF_TOKEN_MATCHES, 1, cache.make_key(key), token)


def held(key: str) -> bool:
	# RedisWrapper.exists applies make_key itself — prefixing here double-scopes
	# the key and the check always misses.
	return bool(frappe.cache().exists(key))


@contextmanager
def guard(key: str, ttl: int):
	"""Yield the lock token (None if not acquired), releasing on exit:

	with guard(session_key(sid), SESSION_LOCK_TTL) as got:
	    if not got:
	        return  # someone else is already running this
	    ...work...
	"""
	token = acquire(key, ttl)
	try:
		yield token
	finally:
		release(key, token)
