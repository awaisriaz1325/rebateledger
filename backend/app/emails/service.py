"""Email adapter + templates (SPEC §4.11). Every email has HTML and plain-text parts.

Sending always happens in the worker (job ``send_email``). The job payload is
sealed (encrypted) because it can contain single-use links.
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Any, Protocol

from jinja2 import Environment, StrictUndefined, select_autoescape
from sqlalchemy.orm import Session

from app.core.config import Environment as Env
from app.core.config import get_settings
from app.workers.jobs import JobContext, enqueue, handler, seal


@dataclass(frozen=True)
class RenderedEmail:
    to: str
    subject: str
    text: str
    html: str


class EmailAdapter(Protocol):
    def send(self, email: RenderedEmail) -> None: ...


class SmtpAdapter:
    def send(self, email: RenderedEmail) -> None:
        s = get_settings()
        msg = EmailMessage()
        msg["From"] = s.email_from
        msg["To"] = email.to
        msg["Subject"] = email.subject
        msg["Message-ID"] = make_msgid(domain="rebateledger.invalid")
        msg.set_content(email.text)
        msg.add_alternative(email.html, subtype="html")
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            if s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if s.smtp_username and s.smtp_password:
                smtp.login(s.smtp_username, s.smtp_password.get_secret_value())
            smtp.send_message(msg)


class MemoryAdapter:
    """Test adapter: keeps sent emails in memory."""

    def __init__(self) -> None:
        self.outbox: list[RenderedEmail] = []

    def send(self, email: RenderedEmail) -> None:
        self.outbox.append(email)


_adapter: EmailAdapter | None = None


def get_adapter() -> EmailAdapter:
    global _adapter
    if _adapter is None:
        _adapter = MemoryAdapter() if get_settings().env is Env.TEST else SmtpAdapter()
    return _adapter


def set_adapter(adapter: EmailAdapter) -> None:
    global _adapter
    _adapter = adapter


# --------------------------------------------------------------------------- templates

_LAYOUT = """<!doctype html><html lang="en"><body style="margin:0;background:#f4f6f5;font-family:Arial,Helvetica,sans-serif;color:#14211c">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #d9e0dc;border-radius:8px">
<tr><td style="padding:24px 32px;border-bottom:1px solid #d9e0dc;font-weight:bold;font-size:16px">{{ product }}</td></tr>
<tr><td style="padding:24px 32px;font-size:15px;line-height:1.55">{{ body }}</td></tr>
<tr><td style="padding:16px 32px;border-top:1px solid #d9e0dc;font-size:12px;color:#5b6b64">{{ footer }}</td></tr>
</table></td></tr></table></body></html>"""

_BUTTON = '<p><a href="{url}" style="display:inline-block;background:#1d4f3c;color:#ffffff;text-decoration:none;padding:10px 18px;border-radius:6px;font-weight:bold">{label}</a></p><p style="font-size:13px;color:#5b6b64">Or paste this link into your browser:<br>{url}</p>'

# name → (subject, text body, html body). Bodies are Jinja templates.
TEMPLATES: dict[str, tuple[str, str, str]] = {
    "invite": (
        "You're invited to {{ org_name }} on {{ product }}",
        "{{ inviter }} invited you to join {{ org_name }} on {{ product }} as {{ role }}.\n\nAccept the invitation: {{ url }}\n\nThis link expires in {{ ttl_days }} days. If you weren't expecting it, ignore this email.",
        "<p>{{ inviter }} invited you to join <strong>{{ org_name }}</strong> on {{ product }} as <strong>{{ role }}</strong>.</p>{{ button('Accept invitation', url) }}<p>This link expires in {{ ttl_days }} days. If you weren't expecting it, ignore this email.</p>",
    ),
    "verify_email": (
        "Confirm your email address",
        "Confirm your email address for {{ product }}: {{ url }}\n\nThe link expires in 24 hours.",
        "<p>Confirm your email address for {{ product }}.</p>{{ button('Confirm email', url) }}<p>The link expires in 24 hours.</p>",
    ),
    "change_email": (
        "Confirm your new email address",
        "Someone asked to change the email on your {{ product }} account to this address. Confirm: {{ url }}\n\nIf this wasn't you, ignore this email.",
        "<p>Someone asked to change the email on your {{ product }} account to this address.</p>{{ button('Confirm new email', url) }}<p>If this wasn't you, ignore this email.</p>",
    ),
    "password_reset": (
        "Reset your {{ product }} password",
        "Reset your password: {{ url }}\n\nThe link expires in {{ ttl_minutes }} minutes and works once. If you didn't ask for this, ignore this email; your password stays the same.",
        "<p>We received a request to reset your password.</p>{{ button('Reset password', url) }}<p>The link expires in {{ ttl_minutes }} minutes and works once. If you didn't ask for this, ignore this email; your password stays the same.</p>",
    ),
    "security_notice": (
        "Security alert: {{ headline }}",
        "{{ headline }}.\n\n{{ detail }}\n\nTime: {{ when }} (UTC)\n\nIf this wasn't you, reset your password now: {{ reset_url }} and contact your administrator.",
        '<p><strong>{{ headline }}.</strong></p><p>{{ detail }}</p><p>Time: {{ when }} (UTC)</p><p>If this wasn\'t you, <a href="{{ reset_url }}">reset your password now</a> and contact your administrator.</p>',
    ),
    "generic": (
        "{{ subject }}",
        "{{ text }}{% if url %}\n\n{{ url }}{% endif %}",
        "<p>{{ text }}</p>{% if url %}{{ button(link_label or 'Open', url) }}{% endif %}",
    ),
}

_env = Environment(
    autoescape=select_autoescape(default=True, default_for_string=True), undefined=StrictUndefined
)
# text/plain part, never rendered as HTML
_text_env = Environment(autoescape=False, undefined=StrictUndefined)  # noqa: S701  # nosec B701


def render(
    template: str, to: str, context: dict[str, Any], *, transactional: bool = True
) -> RenderedEmail:
    from markupsafe import Markup, escape

    product = get_settings().product_name
    ctx = {"product": product, **context}
    subject_t, text_t, html_t = TEMPLATES[template]

    def button(label: str, url: str) -> Markup:
        # inputs escaped
        return Markup(_BUTTON.format(url=escape(url), label=escape(label)))  # noqa: S704  # nosec B704

    subject = _text_env.from_string(subject_t).render(ctx).replace("\n", " ").strip()
    text = _text_env.from_string(text_t).render(ctx)
    body = _env.from_string(html_t).render(button=button, **ctx)
    footer = (
        "You receive this email because of activity on your account. Security emails cannot be turned off."
        if transactional
        else Markup('You can <a href="{}">unsubscribe from these alerts</a>.').format(
            context.get("unsubscribe_url", "")
        )
    )
    # body is autoescaped output
    html = _env.from_string(_LAYOUT).render(product=product, body=Markup(body), footer=footer)  # noqa: S704  # nosec B704
    if not transactional and context.get("unsubscribe_url"):
        text += f"\n\nUnsubscribe from these alerts: {context['unsubscribe_url']}"
    return RenderedEmail(to=to, subject=subject, text=text, html=html)


def queue_email(
    db: Session,
    *,
    to: str,
    template: str,
    context: dict[str, Any],
    tenant_id: Any = None,
    transactional: bool = True,
) -> None:
    """Render later in the worker; the sealed payload is wiped after sending."""
    if template not in TEMPLATES:
        raise KeyError(template)
    enqueue(
        db,
        tenant_id=tenant_id,
        job_type="send_email",
        payload=seal(
            {"to": to, "template": template, "context": context, "transactional": transactional}
        ),
        max_attempts=5,
    )


@handler("send_email")
def _send_email_job(db: Session, ctx: JobContext) -> dict[str, Any]:
    p = ctx.payload
    get_adapter().send(
        render(p["template"], p["to"], p["context"], transactional=p["transactional"])
    )
    return {"sent": True}
