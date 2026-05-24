from fastapi import APIRouter, Depends

from app.modules.ai_assist.schemas import RewriteRequest, RewriteResponse
from app.modules.ai_assist.service import AIAssistService
from app.modules.system.dependencies import verify_token

router = APIRouter()


@router.post("/ai/rewrite", response_model=RewriteResponse)
async def rewrite_message(
    body: RewriteRequest,
    _user: dict = Depends(verify_token),
) -> RewriteResponse:
    """
    Предлагает переработанный вариант сообщения в указанном стиле.
    Stateless — ничего не сохраняет, только возвращает предложение.

    Стили: formal | casual | shorter | clearer | friendly | assertive
    """
    return await AIAssistService.rewrite(text=body.text, style=body.style)
