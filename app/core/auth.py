"""JWT bearer auth dependency for authenticating API requests."""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from config import Config
from extensions import get_async_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_async_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, Config.SECRET_KEY, algorithms=["HS256"])
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except JWTError as err:
        raise credentials_exception from err
    except (ValueError, TypeError) as err:
        raise credentials_exception from err

    from sqlalchemy import select

    from app.models.user import User

    result = await db.execute(select(User).where(User.idu == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    return user
