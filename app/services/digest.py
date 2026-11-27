"""The daily reminder digest: one email per user listing deadlines in the next 3 days."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application
from app.services.email import DIGEST_KIND, EmailMessage
from app.services.email_templates import Brand, checkin_link, layout, text_footer

DIGEST_DAYS = 3
# Rejected and withdrawn roles need no reminder.
ACTIVE_STAGES = ("saved", "applied", "screening", "interview", "offer")
MAX_ITEMS = 20


def today_eat() -> date:
    """Kenya is UTC+3 all year; deadlines are calendar dates there."""
    return (datetime.now(UTC) + timedelta(hours=3)).date()


@dataclass(frozen=True)
class DigestItem:
    role_title: str
    company_name: str
    stage: str
    deadline: date


def upcoming(db: Session, user_id: uuid.UUID, today: date) -> list[DigestItem]:
    """Must run in a session RLS-bound to user_id; the filter is repeated here too."""
    rows = db.scalars(
        select(Application)
        .where(
            Application.user_id == user_id,
            Application.stage.in_(ACTIVE_STAGES),
            Application.deadline >= today,
            Application.deadline <= today + timedelta(days=DIGEST_DAYS),
        )
        .order_by(Application.deadline, Application.role_title)
        .limit(MAX_ITEMS)
    ).all()
    return [
        DigestItem(a.role_title, a.company_name, a.stage, a.deadline)
        for a in rows
        if a.deadline is not None
    ]


def _when(deadline: date, today: date) -> str:
    days = (deadline - today).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days ({deadline.strftime('%a %d %b')})"


def digest_message(
    brand: Brand,
    to: str,
    handle: str,
    items: list[DigestItem],
    today: date,
    *,
    checkin_due: bool = False,
) -> EmailMessage:
    """With checkin_due, the Dira reminder rides along (still one email a day)."""
    count = len(items)
    subject = f"{count} deadline{'s' if count != 1 else ''} coming up: {brand.name}"
    lines = [f"- {i.role_title} at {i.company_name} ({i.stage}): due {_when(i.deadline, today)}"
             for i in items]  # fmt: skip
    app_url = f"{brand.base_url}/"
    settings_url = f"{brand.base_url}/settings"
    checkin_text = (
        ["Your career check-in is also due: " + checkin_link(brand), ""] if checkin_due else []
    )
    text = "\n".join(
        [
            f"Hi {handle},",
            "",
            "These deadlines are in the next 3 days:",
            "",
            *lines,
            "",
            f"Open your tracker: {app_url}",
            "",
            *checkin_text,
            f"Turn these reminders off in Settings: {settings_url}",
            "",
            text_footer(brand),
        ]
    )
    checkin_href = escape(checkin_link(brand), quote=True)
    checkin_html = (
        f'<p>Your career check-in is also due: <a href="{checkin_href}">start it</a>.</p>'
        if checkin_due
        else ""
    )
    rows = "".join(
        f"<li><strong>{escape(i.role_title)}</strong> at {escape(i.company_name)} "
        f"({escape(i.stage)}): due {escape(_when(i.deadline, today))}</li>"
        for i in items
    )
    html = layout(
        brand,
        f"<p>Hi {escape(handle)},</p><p>These deadlines are in the next 3 days:</p>"
        f"<ul>{rows}</ul>"
        f'<p><a href="{escape(app_url, quote=True)}">Open your tracker</a></p>' + checkin_html,
        footer_html="Turn these reminders off in "
        f'<a href="{escape(settings_url, quote=True)}">Settings</a>.',
    )
    return EmailMessage(to=to, subject=subject, text=text, html=html, kind=DIGEST_KIND)
