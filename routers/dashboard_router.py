from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse

from auth import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user=Depends(get_current_user)):
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=303)
    return request.app.state.templates.TemplateResponse("dashboard.html", {"request": request, "user": user})