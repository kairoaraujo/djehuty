"""
Shared handle.net PID registration.

Extracted from ``djehuty.web.wsgi.__register_file_handle`` so the FastAPI
upload handler can register persistent identifiers identically to the
legacy implementation.
"""

from __future__ import annotations

import logging

import requests

from djehuty.web.config import config


_log = logging.getLogger(__name__)


def register_file_handle(handle: str, download_url: str) -> bool:
    """Register ``handle`` to point at ``download_url`` on the handle.net server.

    Returns ``True`` on a 201 response, ``False`` for any other status or
    a connection error. Mirrors the legacy behaviour bit-for-bit.
    """
    if getattr(config, "handle_url", None) is None:
        return False

    handle_data = {
        "values": [
            {
                "index": config.handle_index,
                "type": "URL",
                "data": {
                    "format": "string",
                    "value": download_url,
                },
            }
        ]
    }
    http_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": 'Handle clientCert="true"',
    }

    try:
        response = requests.put(
            f"{config.handle_url}/{handle}",
            headers=http_headers,
            cert=(config.handle_certificate_path, config.handle_private_key_path),
            timeout=60,
            json=handle_data,
        )
        if response.status_code == 201:
            _log.info("Handle %s created.", handle)
            return True
        _log.error(
            "Handle registration failed with %s (%s)",
            response.status_code,
            response.text,
        )
    except requests.exceptions.ConnectionError as error:
        _log.error("Failed to create handle %s due to a connection error.", handle)
        _log.error("Error: %s", error)

    return False
