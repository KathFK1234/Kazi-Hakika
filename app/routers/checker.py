"""The public "Is this job real?" checker: no account, nothing stored.

The pasted ad is checked in memory and dropped; only the domain lookup
cache (domain, registration date) is written. 10 checks a minute per IP,
and the outbound caps in app.services.checking apply per IP too.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.deps import FetcherDep, SystemDb, client_ip, enforce, get_limiter
from app.routers.board import CheckOut
from app.services.checking import run_checks
from app.services.digest import today_eat
from app.services.ratelimit import Limit
from app.services.verify import MAX_TEXT, Ad, parse_link

router = APIRouter(prefix="/api", tags=["checker"])

CHECKS_PER_IP = Limit("checker-ip", 10, 60)

SUMMARIES = {
    "flagged": "Be careful: this looks like a scam. Don't pay anything or send documents.",
    "unverified": "We couldn't confirm everything. Read the warnings before you apply.",
    "verified": "Every check passed. Still apply only through the company's own channels.",
}


class CheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=2048)
    text: str = Field(default="", max_length=MAX_TEXT)
    company: str = Field(default="", max_length=200)
    agency: str | None = Field(default=None, max_length=200)

    @field_validator("url", "agency", mode="before")
    @classmethod
    def _blank(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("url")
    @classmethod
    def _web_link(cls, v: str | None) -> str | None:
        if v is not None and parse_link(v) is None:
            raise ValueError("Use a full link starting with https://")
        return v.strip() if v else v


class CheckResult(BaseModel):
    verdict: Literal["verified", "unverified", "flagged"]
    summary: str
    checks: list[CheckOut]
    lookups_paused: bool


@router.post("/check")
def check_job(body: CheckIn, request: Request, db: SystemDb, fetcher: FetcherDep) -> CheckResult:
    ip = client_ip(request)
    enforce(request, CHECKS_PER_IP, ip)
    if not body.url and not body.text.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Paste the job link, the ad's text, or both.",
        )
    ad = Ad(body.url, body.text, body.company, body.agency)
    run = run_checks(db, fetcher, get_limiter(request), f"ip:{ip}", ad, today_eat())
    return CheckResult(
        verdict=run.verdict,
        summary=SUMMARIES[run.verdict],
        checks=[CheckOut.model_validate(c.as_dict()) for c in run.checks],
        lookups_paused=run.lookups_paused,
    )
