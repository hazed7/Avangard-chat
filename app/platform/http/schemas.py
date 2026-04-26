from pydantic import BaseModel, ConfigDict


class OperationOkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool = True
