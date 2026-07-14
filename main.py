from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from config import SECRET_KEY
from database import engine, async_session, get_db
from models import Base, Role, EvaluationCriteria
from routers import auth_router, profile_router, dashboard_router, project_router, request_router, public_profile_router, review_router, admin_router
from auth import get_current_user


app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
app.state.templates = templates

def status_rus(value):
    mapping = {
        "draft": "Черновик",
        "submitted": "Подана",
        "under_review": "На рецензии",
        "evaluated": "Оценён",
        "archived": "В архиве",
        "open": "Открыта",
        "in_progress": "В работе",
        "closed": "Закрыта",
    }
    return mapping.get(value, value)

templates.env.filters["status_rus"] = status_rus

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as session:
        from sqlalchemy import select
        roles = ["startup", "enterprise", "admin"]
        for role_name in roles:
            result = await session.execute(select(Role).where(Role.name == role_name))
            if not result.scalar_one_or_none():
                session.add(Role(name=role_name))
        await session.commit()
    criteria_names = [
        {"name": "Инновационность", "description": "Насколько идея нова и уникальна", "max_score": 5, "weight": 1.0},
        {"name": "Коммерческий потенциал", "description": "Возможность получения прибыли и масштабирования", "max_score": 5, "weight": 1.0},
        {"name": "Техническая реализуемость", "description": "Наличие технологий и ресурсов для реализации", "max_score": 5, "weight": 1.0},
    ]
    for crit in criteria_names:
        result = await session.execute(select(EvaluationCriteria).where(EvaluationCriteria.name == crit["name"]))
        if not result.scalar_one_or_none():
            session.add(EvaluationCriteria(**crit))
    await session.commit()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user=Depends(get_current_user)):
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

app.include_router(auth_router.router)
app.include_router(profile_router.router)
app.include_router(dashboard_router.router)
app.include_router(project_router.router)
app.include_router(request_router.router)
app.include_router(public_profile_router.router)
app.include_router(review_router.router)
app.include_router(admin_router.router)