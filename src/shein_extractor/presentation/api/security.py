from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status


class ApiKeyVerifier:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def __call__(
        self, provided_key: str | None = Header(None, alias="X-API-Key")
    ) -> None:
        if not self.api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="لم يتم إعداد مفتاح API على الخادم.",
            )
        if provided_key is None or not secrets.compare_digest(
            provided_key,
            self.api_key,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="مفتاح API غير صالح.",
                headers={"WWW-Authenticate": "ApiKey"},
            )
