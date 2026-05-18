from __future__ import annotations

from base64 import b64decode, b64encode
from hashlib import sha256
from os import urandom
from typing import Protocol


class AgentSecretStoreNotConfigured(RuntimeError):
    pass


class AgentSecretCipher(Protocol):
    def encrypt(self, value: str) -> str: ...

    def decrypt(self, value: str) -> str: ...


class AesGcmAgentSecretCipher:
    def __init__(self, encryption_key: str | None) -> None:
        key = str(encryption_key or "").strip()
        if not key:
            raise AgentSecretStoreNotConfigured("agent secret store is not configured")
        self._key = sha256(key.encode("utf-8")).digest()

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as error:
            raise AgentSecretStoreNotConfigured("agent secret encryption dependency is not installed") from error

        nonce = urandom(12)
        encrypted = AESGCM(self._key).encrypt(nonce, value.encode("utf-8"), None)
        return b64encode(nonce + encrypted).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as error:
            raise AgentSecretStoreNotConfigured("agent secret encryption dependency is not installed") from error

        payload = b64decode(value.encode("ascii"))
        nonce = payload[:12]
        encrypted = payload[12:]
        return AESGCM(self._key).decrypt(nonce, encrypted, None).decode("utf-8")
