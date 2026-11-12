"""Seed a demo account so the app is usable the moment it boots.

Run: python -m app.seed
Idempotent — running it twice does not create a second demo user.
"""

from __future__ import annotations

from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.models import User
from app.security import hash_password

DEMO_EMAIL = "demo@jawab.app"
DEMO_PASSWORD = "demo12345"
DEMO_NAME = "Demo Reader"


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing is not None:
            print(f"Demo account already exists: {DEMO_EMAIL}")
            return

        user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(DEMO_PASSWORD),
            display_name=DEMO_NAME,
        )
        db.add(user)
        db.commit()
        print(f"Created demo account: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
