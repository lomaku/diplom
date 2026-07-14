from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import User, StartupProfile, EnterpriseProfile, UserRole
from auth import get_current_user, verify_password, hash_password
from email_utils import send_confirmation_email
import uuid

router = APIRouter(prefix="/profile", tags=["profile"])

@router.get("/", response_class=HTMLResponse)
async def view_profile(request: Request, user=Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    success = request.query_params.get("msg")
    error = request.query_params.get("error")
    message = None
    if success:
        message = "Изменения сохранены." if success == "saved" else "Проверьте почту для подтверждения email." if success == "email_sent" else None
    elif error:
        message = f"Ошибка: {error}"

    return request.app.state.templates.TemplateResponse("profile.html", {
        "request": request,
        "user": user,
        "startup_profile": user.startup_profile,
        "enterprise_profile": user.enterprise_profile,
        "success_message": message
    })

@router.post("/edit")
async def edit_profile(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Перезагружаем пользователя в текущей сессии
    stmt = select(User).options(
        selectinload(User.roles).selectinload(UserRole.role),
        selectinload(User.startup_profile),
        selectinload(User.enterprise_profile)
    ).where(User.id == user.id)
    result = await db.execute(stmt)
    current_user = result.scalar_one()

    form = await request.form()
    print("Form data:", dict(form))  # отладка в консоли

    try:
        # Основное имя
        current_user.name = form.get("name", current_user.name)

        user_roles = {role.role.name for role in current_user.roles}

        # Стартап-профиль
        if "startup" in user_roles and current_user.startup_profile:
            sp = current_user.startup_profile
            sp.team_name = form.get("team_name", sp.team_name)
            sp.description = form.get("description", sp.description)
            sp.website = form.get("website", sp.website)
            founded_year = form.get("founded_year")
            if founded_year and founded_year.isdigit():
                sp.founded_year = int(founded_year)
            else:
                sp.founded_year = None  # или оставить предыдущее, но лучше обнулить

        # Профиль предприятия
        if "enterprise" in user_roles and current_user.enterprise_profile:
            ep = current_user.enterprise_profile
            ep.company_name = form.get("company_name", ep.company_name)
            ep.industry = form.get("industry", ep.industry)
            ep.description = form.get("description", ep.description)
            ep.website = form.get("website", ep.website)

            comp_str = form.get("competencies", "")
            ep.competencies = [c.strip() for c in comp_str.split(",") if c.strip()] if comp_str else []

            exp_years = form.get("experience_years")
            if exp_years and exp_years.isdigit():
                ep.experience_years = int(exp_years)
            else:
                ep.experience_years = None

            ep.is_available = form.get("is_available") == "on"

        await db.commit()
        print("Profile updated successfully")  # отладка
        return RedirectResponse(url="/profile?msg=saved", status_code=303)

    except Exception as e:
        print("Error updating profile:", str(e))  # отладка
        return RedirectResponse(url=f"/profile?error={str(e)}", status_code=303)


@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if not verify_password(current_password, user.password_hash):
        return RedirectResponse(url="/profile?error=Неверный текущий пароль", status_code=303)
    user.password_hash = hash_password(new_password)
    await db.commit()
    return RedirectResponse(url="/profile?msg=saved", status_code=303)

@router.post("/change-email")
async def change_email(
    request: Request,
    new_email: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    # Проверим, не занят ли email
    existing = await db.execute(select(User).where(User.email == new_email))
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/profile?error=Этот email уже используется", status_code=303)

    user.email = new_email
    user.email_confirmed = False
    user.confirmation_token = str(uuid.uuid4())
    await db.commit()
    await send_confirmation_email(user.email, user.name, user.confirmation_token)
    return RedirectResponse(url="/profile?msg=email_sent", status_code=303)