"""Shared Jinja2 templating foundation for the FastAPI UI surface.

Faithful port of the legacy ``djehuty.web.wsgi`` Jinja2 setup and the
``__render_template`` page-context builder. Every UI page (and the auth HTML
error pages) renders through here.

Templates still live at ``djehuty/web/resources/html_templates`` so the legacy
and new stacks share one copy during the migration; this module locates them
via the ``djehuty.web`` package directory (it does NOT import the legacy WSGI
app). ``render_template`` returns an HTML string; the FastAPI glue wraps it in
a response.
"""

import os
import uuid

from jinja2 import Environment, FileSystemLoader

import djehuty.web
from djehuty.web.config import config

# Session cookie names: must match djehuty.auth and the legacy server.
COOKIE_KEY = "djehuty_session"
IMPERSONATOR_COOKIE_KEY = "impersonator_djehuty_session"

# djehuty.web is a namespace package (no __init__.py), so use __path__ rather
# than __file__ to locate its on-disk resources directory.
_RESOURCES = os.path.join(list(djehuty.web.__path__)[0], "resources")

# Mirrors the legacy environment: internal templates first, then "/" so the
# legacy "static page" templates (absolute paths) keep resolving.
jinja = Environment(
    loader=FileSystemLoader([
        os.path.join(_RESOURCES, "html_templates"),
        "/",
    ]),
    autoescape=True,
)


def _impersonating_account(db, token, impersonator_token):
    """Account being impersonated, or ``None`` (faithful to legacy).

    Legacy ``__impersonating_account``: only when an impersonator cookie is
    present does the *current* session token resolve to the impersonated user.
    """
    if impersonator_token is None:
        return None
    return db.account_by_session_token(token)


def page_context(db, token, impersonator_token, path, **context):
    """Build the shared page context, faithful to legacy ``__render_template``."""
    account = db.account_by_session_token(token)
    parameters = {
        "base_url":              config.base_url,
        "nonce":                 uuid.uuid4().hex,
        "identity_provider":     config.identity_provider,
        "in_production":         config.in_production,
        "is_logged_in":          account is not None,
        "may_deposit":           db.is_depositor(token, account),
        "large_footer":          config.large_footer,
        "maintenance_mode":      config.maintenance_mode,
        "menu":                  config.menu,
        "orcid_client_id":       config.orcid_client_id,
        "orcid_endpoint":        config.orcid_endpoint,
        "path":                  path,
        "sandbox_message":       config.sandbox_message,
        "site_description":      config.site_description,
        "site_name":             config.site_name,
        "site_shorttag":         config.site_shorttag,
        "publisher_rors":        config.publisher_rors,
        "support_email_address": config.support_email_address,
        "small_footer":          config.small_footer,
        "startup_timestamp":     config.startup_timestamp,
    }
    if account is None:
        parameters = {**parameters,
            "session_token":         None,
            "impersonating_account": None,
            "is_reviewing":          None,
        }
    else:
        parameters = {**parameters,
            "impersonating_account":  _impersonating_account(db, token, impersonator_token),
            "is_reviewing":           db.may_review(impersonator_token),
            "may_administer":         db.may_administer(token, account),
            "may_impersonate":        db.may_impersonate(token, account),
            "may_query":              db.may_query(token, account),
            "may_review":             db.may_review(token, account),
            "may_review_institution": db.may_review_institution(token, account),
            "may_review_integrity":   db.may_review_integrity(token, account),
            "may_review_quotas":      db.may_review_quotas(token, account),
            "session_token":          token,
        }

        if not parameters["is_reviewing"]:
            parameters["is_reviewing"] = db.may_review_institution(impersonator_token)

    return {**context, **parameters}


def render_template(db, token, impersonator_token, path, template_name, **context) -> str:
    """Render ``template_name`` with the shared page context, returning HTML."""
    template = jinja.get_template(template_name)
    return template.render(page_context(db, token, impersonator_token, path, **context))


def render_plain_template(template_name, **context) -> str:
    """Render ``template_name`` with only the given context (no page chrome).

    Faithful to the legacy ``__render_{css,svg,xml}_template`` helpers, which
    pass an explicit context and no logged-in/privilege information.
    """
    return jinja.get_template(template_name).render(context)
