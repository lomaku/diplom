import os
import uuid
from fastapi import APIRouter, Request, Depends, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import Project, User, ProjectStatus, ProjectReview, ReviewScore, ReviewStatus, EvaluationCriteria
from auth import get_current_user

router = APIRouter(prefix="/projects", tags=["projects"])

@router.get("/create", response_class=HTMLResponse)
async def create_project_form(request: Request, user=Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if "startup" not in [r.role.name for r in user.roles]:
        return HTMLResponse("Доступ запрещён: нужна роль стартапа", status_code=403)
    return request.app.state.templates.TemplateResponse("create_project.html", {"request": request, "user": user})

@router.post("/create")
async def create_project_post(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    stage: str = Form(""),
    tags: str = Form(""),
    image: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if "startup" not in [r.role.name for r in user.roles]:
        return HTMLResponse("Доступ запрещён", status_code=403)

    tags_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    project = Project(
        startup_id=user.id,
        title=title,
        description=description,
        stage=stage,
        tags=tags_list,
        status=ProjectStatus.draft
    )
    db.add(project)
    await db.flush()   # чтобы получить project.id для сохранения файла

    # Сохраняем картинку, если загружена
    image_url = None
    if image and image.filename:
        upload_dir = os.path.join("static", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        ext = os.path.splitext(image.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, "wb") as f:
            content = await image.read()
            f.write(content)
        image_url = f"/static/uploads/{filename}"
        project.image_url = image_url

    await db.commit()
    return RedirectResponse(url="/projects/my", status_code=303)

@router.get("/my", response_class=HTMLResponse)
async def my_projects(request: Request, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    if "startup" not in [r.role.name for r in user.roles]:
        return HTMLResponse("Доступ запрещён", status_code=403)

    stmt = select(Project).where(Project.startup_id == user.id).order_by(Project.created_at.desc())
    result = await db.execute(stmt)
    projects = result.scalars().all()

    return request.app.state.templates.TemplateResponse("my_projects.html", {
        "request": request, "user": user, "projects": projects
    })

@router.get("/{project_id}/edit", response_class=HTMLResponse)
async def edit_project_form(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not user or "startup" not in [r.role.name for r in user.roles]:
        return RedirectResponse(url="/login", status_code=303)

    stmt = select(Project).where(Project.id == project_id, Project.startup_id == user.id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Проект не найден или доступ запрещён", status_code=404)

    return request.app.state.templates.TemplateResponse("edit_project.html", {
        "request": request, "user": user, "project": project
    })

# ---------- Витрина проектов (все оценённые) ----------
@router.get("/", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def all_projects(
    request: Request,
    tag: str = "",
    search: str = "",
    min_score: str = "",
    max_score: str = "",
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    stmt = select(Project).options(selectinload(Project.startup)).where(Project.status == ProjectStatus.evaluated)

    # Поиск по ключевым словам (название + описание)
    if search:
        search_term = f"%{search}%"
        stmt = stmt.where(
            (Project.title.ilike(search_term)) | (Project.description.ilike(search_term))
        )

    # Фильтр по тегу (пересечение массивов)
    if tag:
        stmt = stmt.where(Project.tags.any(tag))

    # Фильтр по рейтингу (overall_score)
    if min_score:
        try:
            min_val = float(min_score)
            stmt = stmt.where(Project.overall_score >= min_val)
        except ValueError:
            pass
    if max_score:
        try:
            max_val = float(max_score)
            stmt = stmt.where(Project.overall_score <= max_val)
        except ValueError:
            pass

    stmt = stmt.order_by(Project.created_at.desc())
    result = await db.execute(stmt)
    projects = result.scalars().all()

    return request.app.state.templates.TemplateResponse("all_projects.html", {
        "request": request,
        "user": user,
        "projects": projects,
        "current_tag": tag,
        "search": search,
        "min_score": min_score,
        "max_score": max_score
    })

# ---------- Детальная страница проекта ----------
@router.get("/{project_id}", response_class=HTMLResponse)
async def project_detail(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    stmt = (
        select(Project)
        .options(
            selectinload(Project.startup).selectinload(User.startup_profile),
            selectinload(Project.reviews).selectinload(ProjectReview.scores).selectinload(ReviewScore.criterion),
            selectinload(Project.reviews).selectinload(ProjectReview.expert)
        )
        .where(Project.id == project_id, Project.status == ProjectStatus.evaluated)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Проект не найден", status_code=404)

    # Собираем комментарии и оценки
    expert_reviews = []
    for review in project.reviews:
        if review.status == ReviewStatus.completed:
            scores_dict = {score.criterion.name: float(score.score) for score in review.scores}
            expert_reviews.append({
                "expert_name": review.expert.name,
                "comment": review.final_comment or "",
                "scores": scores_dict
            })

    return request.app.state.templates.TemplateResponse("project_detail.html", {
        "request": request,
        "user": user,
        "project": project,
        "expert_reviews": expert_reviews
    })

@router.post("/{project_id}/edit")
async def edit_project_post(
    project_id: str,
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    stage: str = Form(""),
    tags: str = Form(""),
    status: str = Form(...),
    image: UploadFile = File(None),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not user or "startup" not in [r.role.name for r in user.roles]:
        return RedirectResponse(url="/login", status_code=303)

    stmt = select(Project).where(Project.id == project_id, Project.startup_id == user.id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        return HTMLResponse("Проект не найден или доступ запрещён", status_code=404)

    project.title = title
    project.description = description
    project.stage = stage
    project.tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

    try:
        project.status = ProjectStatus(status)
    except ValueError:
        return HTMLResponse("Недопустимый статус", status_code=400)

    if image and image.filename:
        upload_dir = os.path.join("static", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        ext = os.path.splitext(image.filename)[1]
        filename = f"{uuid.uuid4()}{ext}"
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, "wb") as f:
            content = await image.read()
            f.write(content)
        project.image_url = f"/static/uploads/{filename}"

    await db.commit()
    return RedirectResponse(url="/projects/my", status_code=303)

@router.post("/{project_id}/delete")
async def delete_project(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not user or "startup" not in [r.role.name for r in user.roles]:
        raise HTTPException(status_code=403, detail="Доступ запрещён")

    stmt = select(Project).where(Project.id == project_id, Project.startup_id == user.id)
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")

    await db.delete(project)
    await db.commit()
    return RedirectResponse(url="/projects/my", status_code=303)