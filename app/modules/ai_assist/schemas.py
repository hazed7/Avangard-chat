from pydantic import BaseModel, Field

from app.modules.ai_assist.enums import RewriteStyle


class RewriteRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    style: RewriteStyle


class RewriteResponse(BaseModel):
    original: str
    rewritten: str
    style: RewriteStyle
