"""Domain errors translated to consistent JSON API responses."""

from __future__ import annotations


class AtlasError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFound(AtlasError):
    status_code = 404
    code = "not_found"


class Forbidden(AtlasError):
    status_code = 403
    code = "forbidden"


class Unauthorized(AtlasError):
    status_code = 401
    code = "unauthorized"


class Conflict(AtlasError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AtlasError):
    status_code = 422
    code = "validation_failed"


class RateLimited(AtlasError):
    status_code = 429
    code = "rate_limited"
