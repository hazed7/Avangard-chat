import io
import uuid

from aiohttp import ClientResponse
from fastapi import UploadFile
from miniopy_async import Minio
from app.platform.config.settings import settings
from app.platform.observability.logger import get_logger

logger = get_logger("s3")

s3_settings = settings.s3
client = Minio(
    endpoint=s3_settings.url,
    access_key=s3_settings.access_key,
    secret_key=s3_settings.secret_key,
    secure=False
)

CONTENT_TYPE_PREFIX_ATTACHMENTS = {
    # images
    "image/jpeg": s3_settings.folder_photos,
    "image/png": s3_settings.folder_photos,
    "image/webp": s3_settings.folder_photos,
    "image/gif": s3_settings.folder_photos,
    "image/heic": s3_settings.folder_photos,
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


async def init_s3():
    buckets = [s3_settings.bucket_avatars, s3_settings.bucket_attachments]
    for bucket in buckets:
        exists = await client.bucket_exists(bucket)
        if not exists:
            await client.make_bucket(bucket)
            logger.info(f"Created bucket: {bucket}")


async def upload_user_avatar(
    user_id: str,
    file: UploadFile,
) -> str:
    object_name = f"{user_id}/{uuid.uuid4()}"
    return await upload_file(settings.s3_bucket_avatars, object_name, file)


async def upload_message_attachment(
    room_id: str,
    file: UploadFile,
) -> str | None:
    if not CONTENT_TYPE_PREFIX_ATTACHMENTS[file.content_type]:
        return None
    object_name = f"{CONTENT_TYPE_PREFIX_ATTACHMENTS[file.content_type]}/{room_id}/{uuid.uuid4()}"
    return await upload_file(settings.s3_bucket_avatars, object_name, file)


async def upload_file(
    bucket: str,
    object_name: str,
    file: UploadFile,
) -> str:
    file_data = await file.read()
    await client.put_object(
        bucket_name=bucket,
        object_name=object_name,
        data=io.BytesIO(file_data),
        length=len(file_data),
        content_type=file.content_type,
    )
    logger.info(f"Uploaded {object_name} to {bucket}")
    return object_name


async def download_file(bucket: str, object_name: str) -> ClientResponse:
    return await client.get_object(
        bucket_name=bucket,
        object_name=object_name,
    )


async def delete_file(bucket: str, object_name: str):
    await client.remove_object(bucket_name=bucket, object_name=object_name)
    logger.info(f"Deleted {object_name} from {bucket}")

