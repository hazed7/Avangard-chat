from functools import lru_cache

from miniopy_async import Minio

from app.platform.backends.s3.service import S3Service
from app.platform.config.settings import settings


@lru_cache
def get_s3_client_singleton() -> Minio:
    s3_settings = settings.s3
    return Minio(
        endpoint=s3_settings.url,
        access_key=s3_settings.access_key,
        secret_key=s3_settings.secret_key,
        secure=False,
    )


@lru_cache()
def get_s3_service_singleton() -> S3Service:
    return S3Service(
        s3_client=get_s3_client_singleton(),
    )
