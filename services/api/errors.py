"""Typed API errors with a machine-readable `code` (see models.ErrorCode)."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from models import ApiError, ErrorCode


class FaultlineError(Exception):
    def __init__(self, code: ErrorCode, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def faultline_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, FaultlineError)
    body = ApiError(code=exc.code, message=exc.message)
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))
