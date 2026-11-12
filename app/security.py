"""Auth primitives and the rate limiter.

Passwords: bcrypt, cost 12. Tokens: HS256 JWT with a `sub` claim holding the
user id. The rate limiter is in-process and keyed by client IP — good enough
for one box, and honest about it: the docstring says so, and the scaling
notes in ARCHITECTURE.md say what to swap it for.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)

# bcrypt silently truncates at 72 bytes; refuse longer input instead of
# letting two different passwords hash the same.
MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        raise ValueError("password too long")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(raw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(user_id: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_token(creds.credentials)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account not found"
        )
    return user


def optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User | None:
    """For endpoints that work signed-out but do more when signed in."""
    if creds is None or not creds.credentials:
        return None
    user_id = decode_token(creds.credentials)
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user if user and user.is_active else None


class RateLimiter:
    """Sliding-window limiter, in memory, per process.

    Fine for a single instance. Behind more than one worker this becomes
    per-worker, which is why production should move it to Redis — noted in
    ARCHITECTURE.md rather than pretended away.
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - self.window
        bucket = self._hits[key]

        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= self.limit:
            retry = int(self.window - (now - bucket[0])) + 1
            return False, max(retry, 1)

        bucket.append(now)
        return True, 0

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)


def client_key(request: Request) -> str:
    """Identify a caller. Trusts X-Forwarded-For only for the first hop."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def rate_limit(request: Request) -> None:
    allowed, retry = limiter.check(client_key(request))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests — slow down a little.",
            headers={"Retry-After": str(retry)},
        )
