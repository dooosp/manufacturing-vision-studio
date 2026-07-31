"""Typed fail-closed errors shared by the local API and Python interface."""

from __future__ import annotations

from typing import Any

_STATUS_BY_CODE = {
    "RESOURCE_NOT_FOUND": 404,
    "PART_ID_MISMATCH": 409,
    "REVISION_MISMATCH": 409,
    "STORAGE_CONFLICT": 409,
}


class MVSError(Exception):
    """Base error with a stable machine-readable code."""

    code = "INTERNAL_ERROR"
    status_code = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
            self.status_code = _STATUS_BY_CODE.get(code, self.status_code)
        self.details = details or {}


class UnsafeInputError(MVSError):
    code = "SCHEMA_INVALID"
    status_code = 422


class NotFoundError(MVSError):
    code = "RESOURCE_NOT_FOUND"
    status_code = 404


class ConflictError(MVSError):
    code = "STORAGE_CONFLICT"
    status_code = 409


class EvidenceError(MVSError):
    code = "EVIDENCE_INCOMPLETE"
    status_code = 422


class IdentityMismatchError(EvidenceError):
    code = "PART_ID_MISMATCH"
    status_code = 409
