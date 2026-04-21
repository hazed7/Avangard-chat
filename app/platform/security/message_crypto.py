import base64
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from app.platform.config.settings import Settings


@dataclass(frozen=True, slots=True)
class EncryptedText:
    ciphertext: str
    nonce: str
    key_id: str
    aad: str


class MessageCrypto:
    def __init__(self, settings: Settings):
        self._active_key_id = settings.message_encryption.active_key_id
        self._keys = {
            key_id: base64.b64decode(encoded_key, validate=True)
            for key_id, encoded_key in settings.message_encryption.keys.items()
        }

    @staticmethod
    def _encode_json(context: dict[str, str]) -> bytes:
        return json.dumps(
            context,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()

    def encrypt(self, text: str, *, context: dict[str, str]) -> EncryptedText:
        nonce = os.urandom(12)
        aad = self._encode_json(context)
        ciphertext = AESGCM(self._keys[self._active_key_id]).encrypt(
            nonce=nonce,
            data=text.encode(),
            associated_data=aad,
        )
        return EncryptedText(
            ciphertext=base64.b64encode(ciphertext).decode(),
            nonce=base64.b64encode(nonce).decode(),
            key_id=self._active_key_id,
            aad=base64.b64encode(aad).decode(),
        )

    def decrypt(
        self,
        *,
        ciphertext: str,
        nonce: str,
        key_id: str,
        aad: str,
        context: dict[str, str],
    ) -> str:
        key = self._keys.get(key_id)
        if not key:
            raise HTTPException(
                status_code=500, detail="Message encryption key not found"
            )

        expected_aad = self._encode_json(context)
        stored_aad = base64.b64decode(aad, validate=True)
        if stored_aad != expected_aad:
            raise HTTPException(
                status_code=500, detail="Message metadata integrity error"
            )

        try:
            decrypted = AESGCM(key).decrypt(
                nonce=base64.b64decode(nonce, validate=True),
                data=base64.b64decode(ciphertext, validate=True),
                associated_data=stored_aad,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500,
                detail="Failed to decrypt message payload",
            ) from exc
        return decrypted.decode()
