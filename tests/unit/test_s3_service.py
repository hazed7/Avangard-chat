import asyncio
import io
from unittest.mock import AsyncMock

from fastapi import UploadFile
from PIL import Image
from starlette.datastructures import Headers

from app.platform.backends.s3.service import (
    AVATAR_CONTENT_TYPE,
    S3Service,
    get_attachment_upload_limit_bytes,
    s3_settings,
)


def _upload_file(data: bytes, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(data),
        filename="avatar.jpg",
        headers=Headers({"content-type": content_type}),
        size=len(data),
    )


def _image_bytes(size: tuple[int, int] = (2048, 2048)) -> bytes:
    image = Image.new("RGB", size, color=(200, 60, 40))
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def _heif_bytes() -> bytes:
    image = Image.new("RGB", (16, 16), color=(40, 120, 200))
    output = io.BytesIO()
    image.save(output, format="HEIF")
    return output.getvalue()


def test_upload_user_avatar_optimizes_image_before_upload():
    client = AsyncMock()
    service = S3Service(client)
    original = _image_bytes()

    object_name = asyncio.run(
        service.upload_user_avatar(
            user_id="user-id",
            file=_upload_file(original, "image/jpeg"),
        )
    )

    assert object_name is not None
    put_kwargs = client.put_object.await_args.kwargs
    assert put_kwargs["content_type"] == AVATAR_CONTENT_TYPE
    assert put_kwargs["length"] < len(original)
    with Image.open(put_kwargs["data"]) as stored:
        assert stored.format == "WEBP"
        assert stored.width <= 1024
        assert stored.height <= 1024


def test_upload_user_avatar_rejects_invalid_image_bytes():
    client = AsyncMock()
    service = S3Service(client)

    object_name = asyncio.run(
        service.upload_user_avatar(
            user_id="user-id",
            file=_upload_file(b"not an image", "image/jpeg"),
        )
    )

    assert object_name is None
    client.put_object.assert_not_awaited()


def test_upload_user_avatar_supports_heic_images():
    client = AsyncMock()
    service = S3Service(client)

    object_name = asyncio.run(
        service.upload_user_avatar(
            user_id="user-id",
            file=_upload_file(_heif_bytes(), "image/heic"),
        )
    )

    assert object_name is not None
    assert client.put_object.await_args.kwargs["content_type"] == AVATAR_CONTENT_TYPE


def test_upload_user_avatar_rejects_too_many_pixels(monkeypatch):
    monkeypatch.setattr(s3_settings, "avatar_max_pixels", 4)
    client = AsyncMock()
    service = S3Service(client)

    object_name = asyncio.run(
        service.upload_user_avatar(
            user_id="user-id",
            file=_upload_file(_image_bytes(size=(16, 16)), "image/jpeg"),
        )
    )

    assert object_name is None
    client.put_object.assert_not_awaited()


def test_attachment_upload_limits_follow_content_type_category(monkeypatch):
    monkeypatch.setattr(s3_settings, "attachment_photo_max_upload_size_bytes", 1)
    monkeypatch.setattr(s3_settings, "attachment_video_max_upload_size_bytes", 2)
    monkeypatch.setattr(s3_settings, "attachment_audio_max_upload_size_bytes", 3)
    monkeypatch.setattr(s3_settings, "attachment_document_max_upload_size_bytes", 4)

    assert get_attachment_upload_limit_bytes("image/jpeg") == 1
    assert get_attachment_upload_limit_bytes("video/mp4") == 2
    assert get_attachment_upload_limit_bytes("audio/mpeg") == 3
    assert get_attachment_upload_limit_bytes("application/pdf") == 4
    assert get_attachment_upload_limit_bytes("application/octet-stream") is None


def test_upload_message_attachment_streams_original_file():
    client = AsyncMock()
    service = S3Service(client)
    file = _upload_file(b"raw attachment bytes", "text/plain")

    object_name = asyncio.run(
        service.upload_message_attachment(
            room_id="room-id",
            file=file,
        )
    )

    assert object_name is not None
    put_kwargs = client.put_object.await_args.kwargs
    assert put_kwargs["data"] is file.file
    assert put_kwargs["length"] == -1
    assert put_kwargs["content_type"] == "text/plain"
