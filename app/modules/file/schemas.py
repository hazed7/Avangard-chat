from pydantic import BaseModel


class AttachmentDownloadRequest(BaseModel):
    message_id: str
    object_name: str
