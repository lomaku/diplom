from fastapi import APIRouter, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid
from datetime import timedelta

from database import get_db
from models import User, Role, UserRole, StartupProfile, EnterpriseProfile
from schemas import UserRegister, UserLogin
from auth import hash_password, verify_password
from email_utils import send_confirmation_email, send_reset_password_email

router = APIRouter(prefix="", tags=["auth"])

@router.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    return request.app.state.templates.TemplateResponse("register.html", {"request": request, "user": None})

@router.post("/register")
async def register_post(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    try:
        data = UserRegister(
            email=form.get("email"),
            password=form.get("password"),
            name=form.get("name"),
            roles=form.getlist("roles")
        )
    except Exception as e:
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request, "user": None, "error": str(e)
        }, status_code=400)

    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request, "user": None, "error": "Пользователь с таким email уже существует"
        }, status_code=400)

    if "consent" not in form:
        return request.app.state.templates.TemplateResponse("register.html", {
            "request": request, "user": None, "error": "Необходимо согласие на обработку персональных данных"
        }, status_code=400)

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        email_confirmed=False,
        confirmation_token=str(uuid.uuid4())
    )
    db.add(user)
    await db.flush()

    for role_name in data.roles:
        role = await db.execute(select(Role).where(Role.name == role_name))
        role = role.scalar_one_or_none()
        if not role:
            continue
        user_role = UserRole(user_id=user.id, role_id=role.id)
        db.add(user_role)

        if role_name == "startup":
            profile = StartupProfile(user_id=user.id, team_name=data.name)
            db.add(profile)
        elif role_name == "enterprise":
            profile = EnterpriseProfile(
                user_id=user.id,
                company_name=data.name,
                competencies=[],
                experience_years=None,
                is_available=False
            )
            db.add(profile)

    await db.commit()

    # Отправляем письмо подтверждения
    await send_confirmation_email(user.email, user.name, user.confirmation_token)

    # Показываем страницу с сообщением
    return request.app.state.templates.TemplateResponse("register.html", {
        "request": request, "user": None,
        "success_message": "Регистрация прошла успешно! Проверьте почту для подтверждения email."
    }, status_code=200)

@router.get("/confirm/{token}", response_class=HTMLResponse)
async def confirm_email(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.confirmation_token == token)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        return HTMLResponse("Неверный или устаревший токен подтверждения.", status_code=400)
    user.email_confirmed = True
    user.confirmation_token = None
    await db.commit()
    return request.app.state.templates.TemplateResponse("login.html", {
        "request": request, "user": None,
        "success_message": "Email подтверждён! Теперь вы можете войти."
    })

@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return request.app.state.templates.TemplateResponse("login.html", {"request": request, "user": None})

@router.post("/login")
async def login_post(request: Request, db: AsyncSession = Depends(get_db)):
    form = await request.form()
    email = form.get("email")
    password = form.get("password")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request, "user": None, "error": "Неверный email или пароль"
        }, status_code=400)

    if not user.email_confirmed:
        return request.app.state.templates.TemplateResponse("login.html", {
            "request": request, "user": None,
            "error": "Email не подтверждён. Проверьте почту или запросите подтверждение повторно."
        }, status_code=400)

    request.session["user_id"] = str(user.id)
    return RedirectResponse(url="/dashboard", status_code=303)

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

# ---------- Забыли пароль ----------
@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_form(request: Request):
    return request.app.state.templates.TemplateResponse("forgot_password.html", {"request": request, "user": None})

@router.post("/forgot-password")
async def forgot_password_submit(request: Request, email: str = Form(...), db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.email == email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if user:
        # Генерируем токен сброса
        token = str(uuid.uuid4())
        user.reset_token = token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        await db.commit()
        await send_reset_password_email(user.email, user.name, token)
    # Всегда показываем одно и то же сообщение, чтобы не раскрывать, существует ли email
    return request.app.state.templates.TemplateResponse("forgot_password.html", {
        "request": request, "user": None,
        "success_message": "Если указанный email зарегистрирован, на него отправлена инструкция по сбросу пароля."
    })

@router.get("/reset-password/{token}", response_class=HTMLResponse)
async def reset_password_form(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.reset_token == token, User.reset_token_expires > datetime.utcnow())
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        return HTMLResponse("Токен сброса недействителен или истёк.", status_code=400)
    return request.app.state.templates.TemplateResponse("reset_password.html", {
        "request": request, "user": None, "token": token
    })

@router.post("/reset-password/{token}")
async def reset_password_submit(token: str, request: Request, password: str = Form(...), db: AsyncSession = Depends(get_db)):
    stmt = select(User).where(User.reset_token == token, User.reset_token_expires > datetime.utcnow())
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        return HTMLResponse("Токен сброса недействителен или истёк.", status_code=400)
    user.password_hash = hash_password(password)
    user.reset_token = None
    user.reset_token_expires = None
    await db.commit()
    return request.app.state.templates.TemplateResponse("login.html", {
        "request": request, "user": None,
        "success_message": "Пароль изменён. Войдите с новым паролем."
    })