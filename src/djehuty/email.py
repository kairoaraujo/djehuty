"""
Shared e-mail helpers.

Extracted from ``djehuty.web.wsgi`` so the FastAPI handlers can send
the same templated e-mails (reviewer-notifications, decline notices,
publication notices, etc.) without depending on the legacy
``ApiServer`` instance.

The module owns:
  - a lazily-constructed :class:`djehuty.web.email_handler.EmailInterface`
    configured from :mod:`djehuty.web.config`;
  - a Jinja environment rooted at the ``email/`` template directory.

Both are singletons-per-process, so the legacy ``server.email`` and
this module's interface effectively share the same SMTP configuration
once :func:`configure_from_config` is invoked at process startup.
"""

from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from djehuty.web import email_handler
from djehuty.web.config import config


_log = logging.getLogger(__name__)

_TEMPLATE_DIR = (
    Path(__file__).resolve().parent / "web" / "resources" / "html_templates"
)

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


_email_interface: email_handler.EmailInterface | None = None


def register_interface(interface: email_handler.EmailInterface) -> None:
    """Register the process-wide configured EmailInterface.

    Called once during application startup (from ``djehuty.web.ui``)
    after the SMTP credentials have been applied to the interface.
    """
    global _email_interface
    _email_interface = interface


def _get_interface() -> email_handler.EmailInterface:
    """Return the registered EmailInterface, or a fresh empty one.

    The fallback is intentionally unconfigured so
    :meth:`EmailInterface.is_properly_configured` returns ``False`` and
    :func:`send_templated_email` short-circuits to ``False`` without
    raising — matching the legacy behaviour when SMTP is not set up.
    """
    if _email_interface is not None:
        return _email_interface
    return email_handler.EmailInterface()


def render_email_templates(template_name: str, **context) -> tuple[str, str]:
    """Render ``<template_name>.html`` and ``<template_name>.txt``.

    ``base_url`` and ``site_name`` are always injected.
    Returns a ``(plain_text, html)`` tuple.
    """
    html_tpl = _jinja_env.get_template(f"{template_name}.html")
    text_tpl = _jinja_env.get_template(f"{template_name}.txt")
    parameters = {"base_url": config.base_url, "site_name": config.site_name}
    return (
        text_tpl.render({**context, **parameters}),
        html_tpl.render({**context, **parameters}),
    )


def send_templated_email(
    db,
    email_addresses,
    subject: str,
    template_name: str,
    **context,
) -> bool:
    """Send ``email/<template_name>`` to ``email_addresses``.

    Respects each recipient's notification opt-out via
    ``db.may_receive_email_notifications`` exactly like the legacy
    handler. Returns ``True`` if every accepted recipient was sent;
    ``False`` otherwise.
    """
    interface = _get_interface()

    if not email_addresses or not interface.is_properly_configured():
        return False

    failure_count = 0
    delivered = 0
    for email_address in email_addresses:
        if not db.may_receive_email_notifications(email_address):
            _log.info(
                "Did not send e-mail to '%s' due to settings.", email_address
            )
            continue
        text, html = render_email_templates(
            f"email/{template_name}",
            recipient_email=email_address,
            **context,
        )
        if interface.send_email(email_address, subject, text, html):
            delivered += 1
        else:
            failure_count += 1

    if failure_count > 0:
        _log.info(
            "Failed to send e-mail to %d out of %d address(es): %s",
            failure_count,
            len(email_addresses),
            subject,
        )
        return False

    _log.info("Sent e-mail to %d address(es): %s", delivered, subject)
    return True


def send_email_to_reviewers(
    db,
    subject: str,
    template_name: str,
    *,
    account_email: str | None = None,
    **context,
) -> bool:
    """Notify every reviewer (and institutional reviewers for the
    depositor's domain, when ``account_email`` is given)."""
    addresses = db.reviewer_email_addresses()
    if account_email is not None:
        try:
            domain = account_email.rsplit("@", 1)[1]
        except IndexError:
            domain = None
        if domain:
            addresses = list(
                set(addresses + db.institutional_reviewer_email_addresses(domain))
            )
    return send_templated_email(
        db,
        addresses,
        subject,
        template_name,
        account_email=account_email,
        **context,
    )


def send_email_to_quota_reviewers(
    db,
    subject: str,
    template_name: str,
    **context,
) -> bool:
    """Notify every account configured to handle quota requests."""
    addresses = db.quota_reviewer_email_addresses()
    return send_templated_email(db, addresses, subject, template_name, **context)
