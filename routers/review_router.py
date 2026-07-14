import uuid
import random
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import (
    Project, User, UserRole, Role, EnterpriseProfile, Request as RequestModel,
    ProjectReview, EvaluationCriteria, ReviewScore, ReviewStatus, ProjectStatus
)
from auth import get_current_user
from email_utils import send_review_invitation, send_review_result

router = APIRouter(tags=["reviews"])

# Количество случайно выбираемых экспертов
N_EXPERTS = 1

@router.post("/projects/{project_id}/submit")
async def submit_project_for_review(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user)
):
    if not user or "startup" not in [r.role.name for r in user.roles]:
        raise HTTPException(status_code=403, detail="Требуется роль стартапа")

    # Получаем проект с его тегами
    result = await db.execute(select(Project).where(Project.id == project_id, Project.startup_id == user.id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    if project.status != ProjectStatus.draft:
        raise HTTPException(status_code=400, detail="Проект уже был отправлен на рецензию")

    # Ищем подходящие предприятия (is_available = True, компетенции пересекаются с тегами проекта)
    project_tags = project.tags if project.tags else []
    if not project_tags:
        raise HTTPException(status_code=400, detail="Проект должен содержать хотя бы один тег")

    # Выбираем готовых экспертов-предприятия, у которых компетенции имеют пересечение с тегами проекта
    # Используем оператор overlap (&&) для массива PostgreSQL
    from sqlalchemy import text
    stmt = (
        select(User)
        .join(EnterpriseProfile, User.id == EnterpriseProfile.user_id)
        .join(UserRole, User.id == UserRole.user_id)
        .join(Role, UserRole.role_id == Role.id)
        .where(Role.name == "enterprise")
        .where(EnterpriseProfile.is_available == True)
        .where(EnterpriseProfile.competencies.overlap(project_tags))  # пересечение массивов
    )
    experts_result = await db.execute(stmt)
    experts = experts_result.scalars().all()

    if len(experts) < N_EXPERTS:
        # Можно взять всех или вернуть ошибку
        selected_experts = experts
    else:
        selected_experts = random.sample(experts, N_EXPERTS)

    if not selected_experts:
        raise HTTPException(status_code=400, detail="Нет доступных экспертов для оценки проекта")

    # Создаём записи рецензий и отправляем приглашения
    for expert in selected_experts:
        token = str(uuid.uuid4())
        review = ProjectReview(
            project_id=project.id,
            expert_id=expert.id,
            review_token=token,
            token_expires=datetime.now(timezone.utc) + timedelta(days=7),
            status=ReviewStatus.assigned
        )
        db.add(review)

        # Формируем ссылку
        review_url = f"http://127.0.0.1:8000/review/{token}"
        # Отправляем письмо (пока без await, можно сделать фоном, но для простоты вызовем)
        try:
            await send_review_invitation(
                recipient_email=expert.email,
                expert_name=expert.name,
                project_title=project.title,
                project_description=project.description or "",
                review_url=review_url
            )
        except Exception as e:
            print(f"Failed to send invitation to {expert.email}: {e}")

    # Меняем статус проекта на submitted
    project.status = ProjectStatus.submitted
    await db.commit()

    return RedirectResponse(url="/projects/my", status_code=303)

# ---------- Страница анкеты по токену ----------
@router.get("/review/{token}", response_class=HTMLResponse)
async def review_form(token: str, request: Request, db: AsyncSession = Depends(get_db)):
    # Проверяем токен
    stmt = (
        select(ProjectReview)
        .options(selectinload(ProjectReview.project))
        .where(ProjectReview.review_token == token)
    )
    result = await db.execute(stmt)
    review = result.scalar_one_or_none()
    if not review:
        return HTMLResponse("Неверный токен рецензии.", status_code=404)
    if review.status == ReviewStatus.completed:
        return HTMLResponse("Вы уже отправили рецензию.", status_code=400)
    if review.token_expires and review.token_expires < datetime.now(timezone.utc):
        return HTMLResponse("Срок действия ссылки истёк.", status_code=400)

    # Получаем активные критерии
    criteria_result = await db.execute(select(EvaluationCriteria).where(EvaluationCriteria.active == True))
    criteria = criteria_result.scalars().all()

    return request.app.state.templates.TemplateResponse("review_form.html", {
        "request": request,
        "review": review,
        "project": review.project,
        "criteria": criteria,
        "token": token
    })

# ---------- Обработка отправленной анкеты ----------
@router.post("/review/{token}")
async def submit_review(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Повторно проверяем токен
    stmt = select(ProjectReview).options(selectinload(ProjectReview.project)).where(ProjectReview.review_token == token)
    result = await db.execute(stmt)
    review = result.scalar_one_or_none()
    if not review or review.status == ReviewStatus.completed:
        return HTMLResponse("Рецензия уже отправлена или ссылка недействительна.", status_code=400)
    if review.token_expires and review.token_expires < datetime.now(timezone.utc):
        return HTMLResponse("Срок действия ссылки истёк.", status_code=400)

    # Получаем критерии
    criteria_result = await db.execute(select(EvaluationCriteria).where(EvaluationCriteria.active == True))
    criteria = criteria_result.scalars().all()

    form = await request.form()
    scores_data = {}
    final_comment = form.get("comment", "")

    # Проверяем и сохраняем оценки
    for criterion in criteria:
        score_str = form.get(f"score_{criterion.id}")
        if score_str is None:
            return HTMLResponse(f"Пожалуйста, заполните оценку для критерия «{criterion.name}».", status_code=400)
        try:
            score = float(score_str)
        except ValueError:
            return HTMLResponse(f"Некорректное значение для критерия «{criterion.name}».", status_code=400)
        if score < 0 or score > criterion.max_score:
            return HTMLResponse(f"Оценка для критерия «{criterion.name}» должна быть от 0 до {criterion.max_score}.", status_code=400)
        scores_data[criterion.id] = score

    # Сохраняем оценки и комментарий
    for criterion_id, score in scores_data.items():
        review_score = ReviewScore(
            review_id=review.id,
            criterion_id=criterion_id,
            score=score
        )
        db.add(review_score)

    review.final_comment = final_comment
    review.status = ReviewStatus.completed
    review.completed_at = datetime.now(timezone.utc)

    await db.commit()

    # Проверяем, все ли рецензии проекта завершены
    project = review.project
    reviews_stmt = select(ProjectReview).where(ProjectReview.project_id == project.id)
    reviews_result = await db.execute(reviews_stmt)
    all_reviews = reviews_result.scalars().all()

    all_completed = all(r.status == ReviewStatus.completed for r in all_reviews)
    if all_completed:
        # Рассчитываем взвешенную оценку проекта
        total_weighted_sum = 0.0
        total_weight = 0.0
        comments = []
        for r in all_reviews:
            # Загружаем оценки для каждой рецензии
            r_scores = await db.execute(
                select(ReviewScore, EvaluationCriteria)
                .join(EvaluationCriteria, ReviewScore.criterion_id == EvaluationCriteria.id)
                .where(ReviewScore.review_id == r.id)
            )
            for rs, crit in r_scores:
                total_weighted_sum += float(rs.score) * float(crit.weight)
                total_weight += float(crit.weight)
            # Собираем комментарий
            expert = await db.execute(select(User).where(User.id == r.expert_id))
            expert_name = expert.scalar_one().name if expert else "Неизвестный"
            comments.append({"expert_name": expert_name, "comment": r.final_comment or "Без комментария"})

        if total_weight > 0:
            overall_score = total_weighted_sum / total_weight
            project.overall_score = overall_score

            # Определяем статус проекта (порог 3.0)
            if overall_score >= 3.0:
                project.status = ProjectStatus.evaluated
            else:
                project.status = ProjectStatus.archived

            # Отправляем уведомление стартапу
            startup = await db.execute(select(User).where(User.id == project.startup_id))
            startup_user = startup.scalar_one()
            try:
                await send_review_result(
                    startup_email=startup_user.email,
                    startup_name=startup_user.name,
                    project_title=project.title,
                    overall_score=overall_score,
                    comments=comments
                )
            except Exception as e:
                print(f"Failed to send result to {startup_user.email}: {e}")

        await db.commit()

    # Возвращаем страницу благодарности
    return HTMLResponse("<h2>Спасибо! Ваша рецензия принята.</h2>")