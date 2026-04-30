import io

from fastapi.openapi.models import Response
from fastapi.testclient import TestClient
from PIL import Image

from tests.helpers.auth import auth_headers


def avatar_image_bytes(
    *,
    size: tuple[int, int] = (16, 16),
    image_format: str = "JPEG",
) -> bytes:
    image = Image.new("RGB", size, color=(120, 40, 200))
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def get_current_user(
    client: TestClient,
    access_token: str,
) -> dict:
    response = client.get(
        "/user/me",
        headers=auth_headers(access_token),
    )
    assert response.status_code == 200
    return response.json()


def upload_avatar(
    client: TestClient,
    access_token: str,
    filename: str = "avatar.jpg",
    content_type: str = "image/jpeg",
    file_content: bytes | None = None,
) -> Response:
    return client.post(
        "/user/me/avatar",
        headers=auth_headers(access_token),
        files={
            "file": (
                filename,
                io.BytesIO(file_content or avatar_image_bytes()),
                content_type,
            ),
        },
    )


def download_avatar(
    client: TestClient,
    access_token: str,
) -> Response:
    return client.get(
        "/user/me/avatar",
        headers=auth_headers(access_token),
    )
