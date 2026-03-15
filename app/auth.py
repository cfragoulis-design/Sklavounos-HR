import os
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AdminUser

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SESSION_KEY = "admin_user_id"
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "sklavounos_hr_session")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def authenticate_admin(db: Session, username: str, password: str) -> Optional[AdminUser]:
    stmt = select(AdminUser).where(AdminUser.username == username)
    user = db.execute(stmt).scalar_one_or_none()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def seed_admin_user(db: Session) -> None:
    admin_user = os.getenv("ADMIN_USER", "admin").strip()
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123").strip()

    stmt = select(AdminUser).where(AdminUser.username == admin_user)
    existing = db.execute(stmt).scalar_one_or_none()
    if existing:
        return

    db.add(
        AdminUser(
            username=admin_user,
            password_hash=hash_password(admin_password),
            is_active=True,
        )
    )
    db.commit()
