import os
import uuid
from fastapi import APIRouter, Request, Depends, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import Request as RequestModel, User, RequestStatus, Response
from auth import get_current_user
from email_utils import send_response_notification

router = APIRouter(prefix="/requests", tags=["requests"])

def check_enterprise(user):
    if not user:
        return False
    return "enterprise" in [r.role.name for r in user.roles]

# ---------- Создание заявки ----------
@router.get("/create", response_class=HTMLResponse)
async def create_request_form(request: Request, user=Depends(get_current_user)):
    if not check_enterprise(user):
        return RedirectResponse(url="/login", status_code=303)
    return request.app.state.templates.TemplateResponse("create_request.html", {"request": request, "user": user})

@router.post("/create")
async def create_request_post(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    requirements: str = Form(""),
    tags: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if not check_enterprise(user):
        return RedirectResponse(url="/login", status_code=303)

    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    req = RequestModel(
        enterprise_id=user.id,
        title=title,
        description=description,
        requirements=requirements,
        tags=tags_list,
        status=RequestStatus.open
    )
    db.add(req)
    await db.commit()
    return RedirectResponse(url="/requests/my", status_code=303)

# ---------- Мои заявки ----------
@router.get("/my", response_class=HTMLResponse)
async def my_requests(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not check_enterprise(user):
        return RedirectResponse(url="/login", status_code=303)

    stmt = select(RequestModel).where(RequestModel.enterprise_id == user.id).order_by(RequestModel.created_at.desc())
    result = await db.execute(stmt)
    requests_list = result.scalars().all()
    return request.app.state.templates.TemplateResponse("my_requests.html", {
        "request": request, "user": user, "requests": requests_list
    })

# ---------- Витрина заявок (все открытые) ----------
@router.get("/", response_class=HTMLResponse)
async def all_requests(
    request: Request,
    tag: str = "",
    search: str = "",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    stmt = select(RequestModel).options(selectinload(RequestModel.enterprise)).where(RequestModel.status == RequestStatus.open)

    # Поиск по ключевым словам
    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            (RequestModel.title.ilike(search_term)) | (RequestModel.description.ilike(search_term))
        )

    # Фильтр по тегу
    if tag:
        stmt = stmt.where(RequestModel.tags.any(tag))

    stmt = stmt.order_by(RequestModel.created_at.desc())
    result = await db.execute(stmt)
    requests_list = result.scalars().all()

    return request.app.state.templates.TemplateResponse("all_requests.html", {
        "request": request,
        "user": user,
        "requests": requests_list,
        "current_tag": tag,
        "search": search
    })

# ---------- Детальная страница заявки ----------
@router.get("/{request_id}", response_class=HTMLResponse)
async def request_detail(
    request_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    stmt = select(RequestModel).options(
        selectinload(RequestModel.enterprise),
        selectinload(RequestModel.responses).selectinload(Response.from_user)
    ).where(RequestModel.id == request_id)
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        return HTMLResponse("Заявка не найдена", status_code=404)

    is_owner = user and req.enterprise_id == user.id
    return request.app.state.templates.TemplateResponse("request_detail.html", {
        "request": request, "user": user, "req": req, "is_owner": is_owner
    })

# ---------- Отправка отклика ----------
@router.post("/{request_id}/respond")
async def respond_to_request(
    request_id: str,
    request: Request,
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    stmt = select(RequestModel).options(selectinload(RequestModel.enterprise)).where(RequestModel.id == request_id)
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()
    if not req or req.status != RequestStatus.open:
        return HTMLResponse("Заявка не найдена или закрыта", status_code=404)

    response = Response(
        from_user_id=user.id,
        request_id=req.id,
        message=message
    )
    db.add(response)
    await db.commit()

    if req.enterprise.email:
        await send_response_notification(
            request_title=req.title,
            recipient_email=req.enterprise.email,
            sender_name=user.name,
            message_text=message
        )

    return RedirectResponse(url=f"/requests/{request_id}", status_code=303)

# ---------- Отклики по всем заявкам предприятия ----------
@router.get("/my/responses", response_class=HTMLResponse)
async def my_responses(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not check_enterprise(user):
        return RedirectResponse(url="/login", status_code=303)

    stmt = (
        select(Response)
        .join(RequestModel, Response.request_id == RequestModel.id)
        .where(RequestModel.enterprise_id == user.id)
        .options(selectinload(Response.request), selectinload(Response.from_user))
        .order_by(Response.created_at.desc())
    )
    result = await db.execute(stmt)
    responses = result.scalars().all()
    return request.app.state.templates.TemplateResponse("my_responses.html", {
        "request": request, "user": user, "responses": responses
    })

# ---------- Редактирование заявки ----------
@router.get("/{request_id}/edit", response_class=HTMLResponse)
async def edit_request_form(
    request_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not check_enterprise(user):
        return RedirectResponse(url="/login", status_code=303)

    stmt = select(RequestModel).where(RequestModel.id == request_id, RequestModel.enterprise_id == user.id)
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        return HTMLResponse("Заявка не найдена или доступ запрещён", status_code=404)
    return request.app.state.templates.TemplateResponse("edit_request.html", {
        "request": request, "user": user, "req": req
    })

@router.post("/{request_id}/edit")
async def edit_request_post(
    request_id: str,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    requirements: str = Form(""),
    tags: str = Form(""),
    status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not check_enterprise(user):
        return RedirectResponse(url="/login", status_code=303)

    stmt = select(RequestModel).where(RequestModel.id == request_id, RequestModel.enterprise_id == user.id)
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()
    if not req:
        return HTMLResponse("Заявка не найдена или доступ запрещён", status_code=404)

    req.title = title
    req.description = description
    req.requirements = requirements
    req.tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    try:
        req.status = RequestStatus(status)
    except ValueError:
        return HTMLResponse("Недопустимый статус", status_code=400)

    await db.commit()
    return RedirectResponse(url="/requests/my", status_code=303)

@router.post("/my/responses/{response_id}/mark-read")
async def mark_response_read(
    response_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not user or "enterprise" not in [r.role.name for r in user.roles]:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    # Находим отклик, принадлежащий заявке предприятия
    stmt = (
        select(Response)
        .join(RequestModel, Response.request_id == RequestModel.id)
        .where(Response.id == response_id, RequestModel.enterprise_id == user.id)
    )
    result = await db.execute(stmt)
    resp = result.scalar_one_or_none()
    if not resp:
        raise HTTPException(status_code=404, detail="Отклик не найден")
    resp.is_read = True
    await db.commit()
    return RedirectResponse(url="/requests/my/responses", status_code=303)