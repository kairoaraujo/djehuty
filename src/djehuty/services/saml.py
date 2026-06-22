"""Framework-neutral SAML 2.0 helpers (faithful port of the legacy machinery).

Extracted AS-IS from ``djehuty.web.wsgi`` (``__request_to_saml_request``,
``__saml_auth``, ``authenticate_using_saml``, and the metadata generation in
``saml_metadata``). No HTTP/framework types belong here -- callers pass the
request primitives (path, GET/POST data) and turn the results into responses.

python3-saml (``onelogin``) and ``xmlsec`` are OPTIONAL dependencies, imported
lazily exactly as legacy does (wsgi.py guards the import with try/except and
defers the real error handling to ``ui``). SAML is only needed when
``identity-provider`` is ``saml``.
"""

import logging

from djehuty.web.config import config

_log = logging.getLogger(__name__)


def saml_available() -> bool:
    """Whether the optional python3-saml dependency can be imported."""
    try:
        import onelogin.saml2.auth  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import
        return True
    except (ImportError, ModuleNotFoundError):
        return False


def request_to_saml_request(path, get_data, post_data) -> dict:
    """Turn request primitives into the dict python3-saml understands.

    Faithful to legacy ``__request_to_saml_request``: always assume HTTPS (a
    proxy may mask it) and override the HTTP host with the configured
    ``base_url`` (stripped of its protocol prefix).
    """
    return {
        "https":       "on",
        "http_host":   config.base_url.split("://")[1],
        "script_name": path,
        "get_data":    get_data,
        "post_data":   post_data,
    }


def _saml_auth(http_fields):
    """Return a OneLogin_Saml2_Auth for the given request fields."""
    from onelogin.saml2.auth import OneLogin_Saml2_Auth  # pylint: disable=import-outside-toplevel
    return OneLogin_Saml2_Auth(http_fields, custom_base_path=config.saml_config_path)


def login_redirect_url(http_fields) -> str:
    """Return the IdP redirect URL to initiate a SAML login (GET /saml/login)."""
    return _saml_auth(http_fields).login()


def sp_metadata(http_fields):
    """Return ``(metadata_xml, errors)`` for the SP metadata document.

    Faithful to legacy ``saml_metadata``. May raise ``xmlsec.Error`` on a
    misconfigured SAML setup -- the caller maps that to HTTP 500, as legacy did.
    """
    saml_auth = _saml_auth(http_fields)
    settings  = saml_auth.get_settings()
    metadata  = settings.get_sp_metadata()
    errors    = settings.validate_metadata(metadata)
    return metadata, errors


def authenticate(db, http_fields):
    """Process a SAML response into an attribute record, or ``None`` on failure.

    Faithful port of legacy ``authenticate_using_saml``: validates the response,
    maps the configured SAML attributes to ``email``/``first_name``/
    ``last_name``/``common_name``, resolves the group/domain from the configured
    groups attribute, and falls back to the e-mail domain. Requires ``email``.
    """
    from onelogin.saml2.auth import OneLogin_Saml2_Auth  # pylint: disable=import-outside-toplevel
    from onelogin.saml2.errors import OneLogin_Saml2_Error  # pylint: disable=import-outside-toplevel

    saml_auth = OneLogin_Saml2_Auth(http_fields, custom_base_path=config.saml_config_path)
    try:
        saml_auth.process_response()
    except OneLogin_Saml2_Error as error:
        if error.code == OneLogin_Saml2_Error.SAML_RESPONSE_NOT_FOUND:
            _log.error("Missing SAMLResponse in POST data.")
        else:
            _log.error("SAML error %d occured.", error.code)
        return None

    errors = saml_auth.get_errors()
    if errors:
        _log.error("Errors in the SAML authentication:")
        _log.error("%s", ", ".join(errors))
        return None

    if not saml_auth.is_authenticated():
        _log.error("SAML authentication failed.")
        return None

    ## Gather SAML session information.
    session = {}
    session['samlNameId']                = saml_auth.get_nameid()
    session['samlNameIdFormat']          = saml_auth.get_nameid_format()
    session['samlNameIdNameQualifier']   = saml_auth.get_nameid_nq()
    session['samlNameIdSPNameQualifier'] = saml_auth.get_nameid_spnq()
    session['samlSessionIndex']          = saml_auth.get_session_index()

    ## Gather attributes from user.
    record            = {}
    attributes        = saml_auth.get_attributes()
    record["session"] = session
    try:
        record["email"]       = attributes[config.saml_attribute_email][0]
        record["first_name"]  = attributes[config.saml_attribute_first_name][0]
        record["last_name"]   = attributes[config.saml_attribute_last_name][0]
        record["common_name"] = attributes[config.saml_attribute_common_name][0]
        record["domain"]      = None
        record["group_uuid"]  = None

        if config.saml_attribute_groups is not None:
            groups = attributes[config.saml_attribute_groups]
            for group in groups:
                prefix = f"{config.saml_attribute_group_prefix}:"
                if group.startswith(prefix):
                    domain = group[len(prefix):].replace("_", ".")
                    group = db.group(association=domain)
                    if group:
                        record["domain"]     = domain
                        record["group_uuid"] = group[0]["uuid"]
                        break

    except (KeyError, IndexError):
        _log.error("Didn't receive expected fields in SAMLResponse.")
        _log.error("Received attributes: %s", attributes)

    if not record["email"]:
        _log.error("Didn't receive required fields in SAMLResponse.")
        _log.error("Received attributes: %s", attributes)
        return None

    # Fall-back to determining the domain based on the e-mail address.
    if record["domain"] is None:
        record["domain"] = record["email"].partition("@")[2]

    return record
