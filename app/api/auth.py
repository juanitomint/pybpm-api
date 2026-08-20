"""FastAPI router for authentication endpoints."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from config import Config
from extensions import get_async_db

router = APIRouter(prefix="/auth", tags=["auth"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def _create_token(user_id: int) -> str:
    expire = dt.datetime.now(dt.UTC) + dt.timedelta(hours=Config.JWT_EXPIRATION_HOURS)
    payload = {"sub": str(user_id), "exp": expire, "iat": dt.datetime.now(dt.UTC)}
    return jwt.encode(payload, Config.SECRET_KEY, algorithm="HS256")


def _verify_password(plain: str, hashed: str) -> bool:
    import bcrypt

    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_async_db),
):
    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (JWTError, ValueError, KeyError) as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from err
    try:
        result = await db.execute(select(User).where(User.idu == user_id))
        found = result.scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 — DB connection failure; return 503.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {exc.__class__.__name__}: {exc}",
            headers={"Retry-After": "5"},
        ) from exc
    
    if not found:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return found


@router.post("/token", response_model=dict)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_db),
) -> dict[str, str]:
    try:
        result = await db.execute(select(User).where(User.nick == form_data.username))
        user = result.scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 — DB connection failure; return 503 with actionable message.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database unavailable: {exc.__class__.__name__}: {exc}",
            headers={"Retry-After": "5"},
        ) from exc
    
    if not user or not _verify_password(form_data.password, user.pass_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = _create_token(user.idu)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=dict)
async def get_me(response: Response, user: User = Depends(get_current_user)):
    response.headers["X-JSON"] = "{}"
    return {
        "idu": user.idu,
        "nick": user.nick,
        "name": user.name,
        "email": user.email,
    }
