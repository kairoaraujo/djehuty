"""Framework-neutral SURF Research Access Management (SRAM) helpers.

Faithful port of the legacy ``__send_sram_collaboration_invite`` and
``__already_in_sram_collaboration`` from ``djehuty.web.wsgi``. Invoked from the
SAML login flow to invite a freshly-authenticated user into the configured SRAM
collaboration. No-ops unless both ``sram_collaboration_id`` and
``sram_organization_api_token`` are configured.
"""

import logging
from datetime import datetime, timedelta

import requests

from djehuty.web.config import config
from djehuty.utils.convenience import value_or_none

_log = logging.getLogger(__name__)


def send_collaboration_invite(saml_record):
    """Invite ``saml_record['email']`` into the configured SRAM collaboration."""
    if (config.sram_organization_api_token is None or
        config.sram_collaboration_id is None or
        "email" not in saml_record):
        return None

    invitation_expiry = datetime.now() + timedelta(days=2)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.sram_organization_api_token}",
        "Content-Type": "application/json"
    }
    json_data = {
        "collaboration_identifier": config.sram_collaboration_id,
        "intended_role": "member",
        # SRAM wants the epoch time in milliseconds.
        "invitation_expiry_date": int(invitation_expiry.timestamp()) * 1000,
        "invites": [saml_record["email"]]
    }
    response = requests.put("https://sram.surf.nl/api/invitations/v1/collaboration_invites",
                            headers = headers,
                            timeout = 60,
                            json    = json_data)
    if response.status_code == 201:
        _log.info("Sent invite to '%s' for SRAM collaboration membership.",
                  saml_record["email"])
    elif response.status_code == 401:
        _log.warning("Missing Authorization for SRAM API.")
    elif response.status_code == 403:
        _log.warning("SRAM API authentication failed.")
    elif response.status_code == 404:
        _log.warning("SRAM API endpoint not found.")
    else:
        _log.info("SRAM unexpectedly responded with: %s", response.status_code)

    return None


def already_in_collaboration(saml_record):
    """Whether ``saml_record['email']`` is an active member of the collaboration."""
    if (config.sram_organization_api_token is None or
        config.sram_collaboration_id is None or
        "email" not in saml_record):
        return None

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {config.sram_organization_api_token}",
        "Content-Type": "application/json"
    }
    response = requests.get(f"https://sram.surf.nl/api/collaborations/v1/{config.sram_collaboration_id}",
                            headers = headers,
                            timeout = 60)
    if response.status_code != 200:
        _log.error("Retrieving SRAM collaboration members failed with status code %s",
                   response.status_code)
        return False

    try:
        record = response.json()
        memberships = record["collaboration_memberships"]
        for member in memberships:
            expiry_date = value_or_none(member, "expiry_date")
            if expiry_date is not None and expiry_date < datetime.now().timestamp():
                continue
            if saml_record["email"].lower() == member["user"]["email"].lower():
                _log.info("Account '%s' is already part of an SRAM collaboration.",
                          saml_record["email"])
                return True
    except (TypeError, KeyError) as error:
        _log.error("Checking SRAM response failed with %s.", error)
        return False

    return False
