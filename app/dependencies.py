from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import SESSION_KEY
from app.database import get_db_session
from app.models import AdminUser


def get_db() -> Session:
    yield from get_db_session()


def get_current_admin(request: Request, db: Session = Depends(get_db)) -> AdminUser:
    admin_id = request.session.get(SESSION_KEY)
    if not admin_id:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, detail="Not authenticated", headers={"Location": "/login"})

    user = db.get(AdminUser, admin_id)
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, detail="Invalid session", headers={"Location": "/login"})
    return user
