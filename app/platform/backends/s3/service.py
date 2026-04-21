import uuid

from aiohttp import ClientResponse
from fastapi import UploadFile
from miniopy_async import Minio
from app.platform.config.settings import settings
from app.platform.observability.logger import get_logger

logger = get_logger("s3")
s3_settings = settings.s3

CONTENT_TYPE_AVATAR = [
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
]

CONTENT_TYPE_PREFIX_ATTACHMENTS = {
    # images
    "image/jpeg": s3_settings.folder_photos,
    "image/png": s3_settings.folder_photos,
    "image/webp": s3_settings.folder_photos,
    "image/gif": s3_settings.folder_photos,
    "image/heic": s3_settings.folder_photos,
    "image/heif": s3_settings.folder_photos,
    # videos
    "video/mp4": s3_settings.folder_video,
    "video/quicktime": s3_settings.folder_video,
    "video/x-msvideo": s3_settings.folder_video,
    "video/webm": s3_settings.folder_video,
    # audio
    "audio/mpeg": s3_settings.folder_audio,
    "audio/ogg": s3_settings.folder_audio,
    "audio/wav": s3_settings.folder_audio,
    "audio/webm": s3_settings.folder_audio,
    "audio/aac": s3_settings.folder_audio,
    # documents
    "application/pdf": s3_settings.folder_documents,
    "application/msword": s3_settings.folder_documents,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": s3_settings.folder_documents,
    "application/vnd.ms-powerpoint": s3_settings.folder_documents,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": s3_settings.folder_documents,
    "application/vnd.apple.pages": s3_settings.folder_documents,
    "application/vnd.apple.keynote": s3_settings.folder_documents,
    "application/vnd.ms-excel": s3_settings.folder_documents,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": s3_settings.folder_documents,
    "application/zip": s3_settings.folder_documents,
    "text/plain": s3_settings.folder_documents,
    "text/csv": s3_settings.folder_documents,
}


class S3Service:
    def __init__(self, s3_client: Minio):
        self.s3_client = s3_client

    async def init_s3(self):
        buckets = [s3_settings.bucket_avatars, s3_settings.bucket_attachments]
        for bucket in buckets:
            exists = await self.s3_client.bucket_exists(bucket)
            if not exists:
                await self.s3_client.make_bucket(bucket)
                logger.info(f"Created bucket: {bucket}")

    async def upload_user_avatar(
        self,
        user_id: str,
        file: UploadFile,
    ) -> str | None:
        object_name = f"{user_id}/{uuid.uuid4()}"
        return await self._upload_file(
            bucket=settings.s3_bucket_avatars,
            object_name=object_name,
            file=file,
        )

    async def upload_message_attachment(
        self,
        room_id: str,
        file: UploadFile,
    ) -> str | None:
        if not CONTENT_TYPE_PREFIX_ATTACHMENTS[file.content_type]:
            return None
        object_name = f"{CONTENT_TYPE_PREFIX_ATTACHMENTS[file.content_type]}/{room_id}/{uuid.uuid4()}"
        return await self._upload_file(
            bucket=settings.s3_bucket_attachments,
            object_name=object_name,
            file=file,
        )

    async def download_file(self, bucket: str, object_name: str) -> ClientResponse:
        return await self.s3_client.get_object(
            bucket_name=bucket,
            object_name=object_name,
        )

    async def delete_file(self, bucket: str, object_name: str):
        await self.s3_client.remove_object(bucket_name=bucket, object_name=object_name)
        logger.info(f"Deleted {object_name} from {bucket}")

    async def _upload_file(
        self,
        bucket: str,
        object_name: str,
        file: UploadFile,
    ) -> str:
        await self.s3_client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=file.file,
            length=-1,
            part_size=10 * 1024 * 1024,
            content_type=file.content_type,
        )
        logger.info(f"Uploaded {object_name} to {bucket}")
        return object_name
