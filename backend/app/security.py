"""Identity, ownership and rate limiting.

A visitor is identified by a high-entropy token (HttpOnly cookie for the web UI,
X-API-Key header for programmatic use). Only its SHA-256 is stored with a scan.
"""
import hashlib
import re
import secrets

from fastapi import Depends, HTTPException, Request, Response
from redis import Redis

from . import config, db

TOKEN_RE = re.compile(r"^ss_[A-Za-z0-9_-]{43}$")
COOKIE = "ss_owner"
_redis: Redis | None = None


def new_token() -> str:
    return "ss_" + secrets.token_urlsafe(32)


def _r() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(config.REDIS_URL, socket_timeout=1)
    return _redis


def client_ip(request: Request) -> str:
    # Only ingress-nginx can reach the API (NetworkPolicy), so X-Real-IP is trusted.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def hit(key: str, limit: int, window: int, fail_open: bool = True) -> None:
    try:
        r = _r()
        n = r.incr(key)
        if n == 1:
            r.expire(key, window)
        if n > limit:
            retry = max(1, r.ttl(key))
            raise HTTPException(429, "rate limit exceeded", headers={"Retry-After": str(retry)})
    except HTTPException:
        raise
    except Exception:
        if not fail_open:
            raise HTTPException(503, "service temporarily unavailable")


def owner(request: Request, response: Response) -> str:
    key = request.headers.get("x-api-key")
    if key is not None:
        if not TOKEN_RE.match(key):
            raise HTTPException(401, "invalid API key")
        h = hashlib.sha256(key.encode()).hexdigest()
        try:
            info = db.resolve_key(h)
        except Exception:
            raise HTTPException(503, "service temporarily unavailable")
        if info and info["revoked"]:
            raise HTTPException(401, "API key revoked")
        return info["owner"] if info else h
    else:
        token = request.cookies.get(COOKIE, "")
        if not TOKEN_RE.match(token):
            token = new_token()
            response.set_cookie(COOKIE, token, max_age=31536000, httponly=True,
                                samesite="lax", secure=config.COOKIE_SECURE, path="/")
    return hashlib.sha256(token.encode()).hexdigest()


def session_owner(request: Request, response: Response) -> str:
    """Owner for key management: browser session only (a leaked key must not mint more keys)."""
    if request.headers.get("x-api-key") is not None:
        raise HTTPException(403, "manage API keys from the web session, not with a key")
    return owner(request, response)


def limit_reads(who: str = Depends(owner)) -> str:
    hit(f"rl:r:{who}", config.RATE_READS_PER_MIN, 60)
    return who


def limit_scans(request: Request, who: str = Depends(owner)) -> str:
    hit(f"rl:s:{who}", config.RATE_SCANS_PER_HOUR, 3600, fail_open=False)
    hit(f"rl:si:{client_ip(request)}", config.RATE_SCANS_PER_HOUR_IP, 3600, fail_open=False)
    return who
