"""Framework-neutral ORCID authentication helpers (faithful port).

Extracted AS-IS from ``djehuty.web.wsgi`` (``authenticate_using_orcid`` and the
authorize redirect built in ``ui_account_home``). No HTTP/framework types here;
the caller passes the authorization ``code`` and turns the result into a
response. Uses plain ``requests`` -- ORCID needs no optional dependency.
"""

import logging

import requests

from djehuty.web.config import config
from djehuty.web import validator

_log = logging.getLogger(__name__)


def authorize_url(redirect_path: str = "/login") -> str:
    """Return the ORCID authorize URL to redirect an anonymous visitor to.

    Faithful to the redirect built in legacy ``ui_account_home``.
    """
    return (f"{config.orcid_endpoint}/authorize?client_id="
            f"{config.orcid_client_id}&response_type=code"
            "&scope=/authenticate&redirect_uri="
            f"{config.base_url}{redirect_path}")


def authenticate(code, redirect_path: str = "/login"):
    """Exchange an authorization ``code`` for an ORCID record, or ``None``.

    Faithful port of legacy ``authenticate_using_orcid``: POSTs to the ORCID
    token endpoint and returns the JSON record (``orcid``, ``name``, ...) on a
    200 response, ``None`` otherwise.
    """
    record = {"code": code}
    try:
        url_parameters = {
            "client_id":     config.orcid_client_id,
            "client_secret": config.orcid_client_secret,
            "grant_type":    "authorization_code",
            "redirect_uri":  f"{config.base_url}{redirect_path}",
            "code":          validator.string_value(record, "code", 0, 10, required=True)
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        response = requests.post(f"{config.orcid_endpoint}/token",
                                 params  = url_parameters,
                                 headers = headers,
                                 timeout = 10)

        if response.status_code == 200:
            return response.json()

        _log.error("ORCID response was %d", response.status_code)
    except validator.ValidationException:
        _log.error("ORCID parameter validation error")

    return None
