"""API documentation page."""

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api-docs")
async def api_docs_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "api.html", {"request": request}
    )
