"""Database errors are logged by code and constraint only.

Postgres puts the failing row in its error detail ("Failing row contains
(email, ...)"), so the message itself must never reach the logs.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

log = logging.getLogger("app.errors")


def describe_db_error(exc: BaseException) -> str:
    """Safe to log: the SQLSTATE and constraint name, never values."""
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or "unknown"
    diag = getattr(orig, "diag", None)
    constraint = getattr(diag, "constraint_name", None) or "-"
    table = getattr(diag, "table_name", None) or "-"
    return f"{type(orig or exc).__name__} sqlstate={sqlstate} table={table} constraint={constraint}"


async def database_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error(
        "database error on %s %s: %s", request.method, request.url.path, describe_db_error(exc)
    )
    return JSONResponse({"detail": "Something went wrong. Please try again."}, status_code=500)
