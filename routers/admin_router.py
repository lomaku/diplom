from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import EvaluationCriteria
from auth import get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])

def check_admin(user):
    return user and "admin" in [r.role.name for r in user.roles]

@router.get("/criteria", response_class=HTMLResponse)
async def list_criteria(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not check_admin(user):
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    result = await db.execute(select(EvaluationCriteria).order_by(EvaluationCriteria.id))
    criteria = result.scalars().all()
    return request.app.state.templates.TemplateResponse("admin_criteria.html", {
        "request": request, "user": user, "criteria": criteria
    })

@router.get("/criteria/add", response_class=HTMLResponse)
async def add_criteria_form(request: Request, user=Depends(get_current_user)):
    if not check_admin(user):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    return request.app.state.templates.TemplateResponse("admin_criteria_form.html", {
        "request": request, "user": user, "criterion": None
    })

@router.post("/criteria/add")
async def add_criteria_submit(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    max_score: float = Form(...),
    weight: float = Form(...),
    active: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not check_admin(user):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    criterion = EvaluationCriteria(
        name=name,
        description=description,
        max_score=max_score,
        weight=weight,
        active=active
    )
    db.add(criterion)
    await db.commit()
    return RedirectResponse(url="/admin/criteria", status_code=303)

@router.get("/criteria/{criterion_id}/edit", response_class=HTMLResponse)
async def edit_criteria_form(
    criterion_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not check_admin(user):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    result = await db.execute(select(EvaluationCriteria).where(EvaluationCriteria.id == criterion_id))
    criterion = result.scalar_one_or_none()
    if not criterion:
        raise HTTPException(status_code=404, detail="Критерий не найден")
    return request.app.state.templates.TemplateResponse("admin_criteria_form.html", {
        "request": request, "user": user, "criterion": criterion
    })

@router.post("/criteria/{criterion_id}/edit")
async def edit_criteria_submit(
    criterion_id: int,
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    max_score: float = Form(...),
    weight: float = Form(...),
    active: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not check_admin(user):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    result = await db.execute(select(EvaluationCriteria).where(EvaluationCriteria.id == criterion_id))
    criterion = result.scalar_one_or_none()
    if not criterion:
        raise HTTPException(status_code=404, detail="Критерий не найден")
    criterion.name = name
    criterion.description = description
    criterion.max_score = max_score
    criterion.weight = weight
    criterion.active = active
    await db.commit()
    return RedirectResponse(url="/admin/criteria", status_code=303)

@router.post("/criteria/{criterion_id}/toggle-active")
async def toggle_criteria_active(
    criterion_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not check_admin(user):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    result = await db.execute(select(EvaluationCriteria).where(EvaluationCriteria.id == criterion_id))
    criterion = result.scalar_one_or_none()
    if criterion:
        criterion.active = not criterion.active
        await db.commit()
    return RedirectResponse(url="/admin/criteria", status_code=303)