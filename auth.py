import bcrypt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import User, UserRole, Response, Request as RequestModele

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    result = await db.execute(
        select(User)
        .options(
            selectinload(User.roles).selectinload(UserRole.role),
            selectinload(User.startup_profile),
            selectinload(User.enterprise_profile)
        )
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user and "enterprise" in [r.role.name for r in user.roles]:
        from models import Response, Request as RequestModel
        count_stmt = (
            select(Response)
            .join(RequestModel, Response.request_id == RequestModel.id)
            .where(RequestModel.enterprise_id == user.id, Response.is_read == False)
        )
        count_result = await db.execute(count_stmt)
        user.unread_count = len(count_result.scalars().all())
    elif user:
        user.unread_count = 0

    return user
    
async def require_roles(roles: list[str], user: User = Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    user_roles = {role.role.name for role in user.roles}
    if not any(role in user_roles for role in roles):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return user