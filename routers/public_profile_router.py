from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import User, Project, Request as RequestModel, UserRole
from auth import get_current_user

router = APIRouter(prefix="/user", tags=["public_profile"])

@router.get("/{user_id}", response_class=HTMLResponse)
async def public_profile(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)  # может быть None
):
    # Загружаем пользователя с ролями и обоими профилями
    stmt = (
        select(User)
        .options(
            selectinload(User.roles).selectinload(UserRole.role),
            selectinload(User.startup_profile),
            selectinload(User.enterprise_profile),
        )
        .where(User.id == user_id)
    )
    result = await db.execute(stmt)
    profile_user = result.scalar_one_or_none()
    if not profile_user:
        return HTMLResponse("Пользователь не найден", status_code=404)

    # Загружаем проекты, если это стартап
    projects = []
    if profile_user.startup_profile:
        stmt_proj = (
            select(Project)
            .where(Project.startup_id == profile_user.id)
            .order_by(Project.created_at.desc())
        )
        proj_result = await db.execute(stmt_proj)
        projects = proj_result.scalars().all()

    # Загружаем заявки, если предприятие
    requests_list = []
    if profile_user.enterprise_profile:
        stmt_req = (
            select(RequestModel)
            .where(RequestModel.enterprise_id == profile_user.id, RequestModel.status == 'open')
            .order_by(RequestModel.created_at.desc())
        )
        req_result = await db.execute(stmt_req)
        requests_list = req_result.scalars().all()

    return request.app.state.templates.TemplateResponse("public_profile.html", {
        "request": request,
        "user": current_user,
        "profile_user": profile_user,
        "projects": projects,
        "requests": requests_list,
    })