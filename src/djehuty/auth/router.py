"""Authentication routes: /login, /saml/login, /logout, /saml/metadata.

Faithful AS-IS port of the legacy ``ui_login`` / ``ui_logout`` /
``saml_metadata`` handlers from ``djehuty.web.wsgi``. Success paths (cookie +
redirect) are byte-for-byte faithful; the redirect targets (``/my/dashboard``,
``/my/sessions/.../activate``) stay legacy-served until the UI surface is ported.

Error paths go through the shared ``djehuty.views.errors`` helpers, which render
the HTML error pages (403.html / 404.html) for HTML clients and fall back to
JSON/plain for everyone else, exactly as legacy did.
"""

import logging

import requests
from fastapi import APIRouter, Request, Depends
from fastapi.responses import Response, RedirectResponse

from djehuty.web.config import config
from djehuty.api.dependencies import get_db
from djehuty.services import saml as saml_service
from djehuty.services import orcid as orcid_service
from djehuty.services import sram as sram_service
from djehuty.services import email as email_service
from djehuty.services.content_negotiation import accepts_html, accepts_content_type, accepts_xml
from djehuty.views import errors
from djehuty.utils.convenience import value_or, value_or_none

_log = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])

# Cookie names -- must match djehuty.api.dependencies and the legacy server.
COOKIE_KEY = "djehuty_session"
IMPERSONATOR_COOKIE_KEY = "impersonator_djehuty_session"


def _login_response(db, account_uuid, account) -> Response:
    """Create the session, set the cookie, and redirect -- faithful to legacy.

    Returns the 2FA-activation redirect when an MFA token is issued, otherwise a
    redirect to the dashboard. ``account`` may be ``None`` (looked up for the
    2FA e-mail when needed).
    """
    token, mfa_token, session_uuid = db.insert_session(account_uuid, name="Website login")
    if session_uuid is None:
        return errors.error_500(f"Failed to create a session for account {account_uuid}.")

    _log.info("Created session %s for account %s.", session_uuid, account_uuid)

    if mfa_token is None:
        response = RedirectResponse("/my/dashboard", status_code=302)
        response.set_cookie(key=COOKIE_KEY, value=token, secure=config.in_production)
        return response

    ## Send e-mail
    if account is None:
        account = db.account_by_uuid(account_uuid)
    email_service.send_templated_email(
        db,
        [account["email"]],
        "Two-factor authentication log-in token",
        "2fa_token", token=mfa_token)

    response = RedirectResponse(f"/my/sessions/{session_uuid}/activate", status_code=302)
    response.set_cookie(key=COOKIE_KEY, value=token, secure=config.in_production)
    return response


@router.api_route("/login", methods=["GET", "POST"], summary="Log in",
                  include_in_schema=False)
@router.api_route("/saml/login", methods=["GET", "POST"], include_in_schema=False)
async def ui_login(request: Request, db=Depends(get_db)):
    """Implements /login (and the /saml/login alias)."""

    account_uuid = None
    account      = None
    accept       = request.headers.get("Accept")

    ## Automatic log in for development purposes only.
    ## --------------------------------------------------------------------
    if config.automatic_login_email is not None and not config.in_production:
        account = db.account_by_email(config.automatic_login_email)
        if account is None:
            return errors.error_403(db, request)
        account_uuid = account["uuid"]
        _log.info("Account %s logged in via auto-login.", account_uuid)

    ## ORCID authentication
    ## --------------------------------------------------------------------
    elif config.identity_provider == "orcid":
        form = await request.form()
        code = value_or_none(form, "code")
        if code is None:
            code = request.query_params.get("code")
        orcid_record = orcid_service.authenticate(code)
        if orcid_record is None:
            return errors.error_403(db, request, "Failed login attempt through ORCID.")

        if not accepts_html(accept):
            return errors.error_406("text/html")

        account_uuid = db.account_uuid_by_orcid(orcid_record['orcid'])
        if account_uuid is None:
            try:
                account_uuid = db.insert_account(
                    # We don't receive the user's e-mail address, so we construct
                    # an artificial one that doesn't resolve so no accidental
                    # e-mails will be sent.
                    email       = f"{orcid_record['orcid']}@orcid",
                    common_name = orcid_record["name"],
                    orcid_id    = orcid_record['orcid']
                )
                if not account_uuid:
                    return errors.error_403(db, request, f"Failed to create account for {orcid_record['orcid']}.")
                _log.info("Account %s created via ORCID.", account_uuid)
            except KeyError:
                return errors.error_403(db, request, "Received an unexpected record from ORCID.")
        else:
            _log.info("Account %s logged in via ORCID.", account_uuid)

    ## SAML 2.0 authentication
    ## --------------------------------------------------------------------
    elif config.identity_provider == "saml":

        ## Initiate the login procedure.
        if request.method == "GET":
            http_fields = saml_service.request_to_saml_request(
                request.url.path, dict(request.query_params), {})
            redirect_url = saml_service.login_redirect_url(http_fields)
            return RedirectResponse(redirect_url, status_code=302)

        ## Retrieve signed data from the IdP via the user.
        if request.method == "POST":
            if not accepts_html(accept):
                return errors.error_406("text/html")

            form = await request.form()
            http_fields = saml_service.request_to_saml_request(
                request.url.path, dict(request.query_params), dict(form))
            saml_record = saml_service.authenticate(db, http_fields)
            if saml_record is None:
                return errors.error_403(db, request, "Failed to receive SAML record.")

            try:
                if "email" not in saml_record:
                    return errors.error_400("Invalid request", "MissingEmailProperty")

                account = db.account_by_email(saml_record["email"].lower())
                if account:
                    account_uuid = account["uuid"]

                    # Reset previous group association.
                    if value_or_none(saml_record, "domain") is None:
                        saml_record["domain"] = ""

                    if not db.update_account(account_uuid, domain=saml_record["domain"]):
                        _log.error("Unable to update domain for account:%s", account_uuid)
                    else:
                        _log.info("Updated domain to '%s' for account:%s.",
                                  saml_record["domain"], account_uuid)

                        # When a dataset was created before the owner was placed
                        # in a group, assign those datasets to the group.
                        datasets = db.datasets(account_uuid = account_uuid,
                                               is_published = False,
                                               limit        = 10000,
                                               use_cache    = False)
                        for dataset in datasets:
                            if "group_name" not in dataset:
                                db.associate_dataset_with_group(dataset["uri"],
                                                                saml_record["domain"],
                                                                account_uuid)

                        # The supervisor privileges are defined in the XML configuration.
                        if (value_or_none(saml_record, "group_uuid") is not None and
                            db.insert_group_member(saml_record["group_uuid"],
                                                   account_uuid, False)):
                            _log.info("Added account:%s to group group:%s.",
                                      account_uuid, saml_record["group_uuid"])
                        else:
                            _log.info("Failed to add account:%s to group group:%s.",
                                      account_uuid, value_or_none(saml_record, "group_uuid"))

                    _log.info("Account %s logged in via SAML.", account_uuid)
                else:
                    account_uuid = db.insert_account(
                        email       = saml_record["email"],
                        first_name  = value_or_none(saml_record, "first_name"),
                        last_name   = value_or_none(saml_record, "last_name"),
                        common_name = value_or_none(saml_record, "common_name"),
                        domain      = value_or_none(saml_record, "domain")
                    )
                    if account_uuid is None:
                        return errors.error_500(f"Creating account for {saml_record['email']} failed.")
                    _log.info("Account %s created via SAML.", account_uuid)

                if (config.sram_collaboration_id is not None and
                    config.sram_organization_api_token is not None):
                    try:
                        if not sram_service.already_in_collaboration(saml_record):
                            sram_service.send_collaboration_invite(saml_record)
                    except (TypeError, KeyError) as error:
                        _log.warning("An error (%s) occurred when sending invite to %s.",
                                     error, value_or_none(saml_record, "email"))
                    except requests.exceptions.ConnectionError:
                        _log.error("Failed to send invite through SRAM due to a connection error.")

                # For a while we didn't create author records for accounts. This
                # check creates the missing author records upon login for such
                # accounts.
                authors = db.authors(account_uuid=account_uuid, limit=1)
                if not value_or(authors, 0, True):
                    author_uuid = db.insert_author(
                        account_uuid = account_uuid,
                        first_name   = value_or_none(saml_record, "first_name"),
                        last_name    = value_or_none(saml_record, "last_name"),
                        full_name    = value_or_none(saml_record, "common_name"),
                        email        = saml_record["email"],
                        is_active    = True,
                        is_public    = True)
                    _log.info("Created author record %s for account %s.",
                              author_uuid, account_uuid)

            except TypeError:
                pass
    else:
        return errors.error_500(f"Unknown identity provider '{config.identity_provider}'.")

    if account_uuid is not None:
        return _login_response(db, account_uuid, account)

    return errors.error_500("Failed to complete the log in procedure for an unknown reason.")


@router.get("/logout", summary="Log out", include_in_schema=False)
def ui_logout(request: Request, db=Depends(get_db)):
    """Implements /logout."""
    if not accepts_html(request.headers.get("Accept")):
        return errors.error_406("text/html")

    # When impersonating, find the admin's token, and set it as the new
    # session token.
    other_session_token = request.cookies.get(IMPERSONATOR_COOKIE_KEY)
    redirect_to         = request.cookies.get("redirect_to")
    session_token       = request.cookies.get(COOKIE_KEY)
    if other_session_token:
        if redirect_to:
            response = RedirectResponse(redirect_to, status_code=302)
        else:
            response = RedirectResponse("/admin/users", status_code=302)

        db.delete_session(session_token)
        response.set_cookie(key    = COOKIE_KEY,
                            value  = other_session_token,
                            secure = config.in_production)
        response.delete_cookie(key = IMPERSONATOR_COOKIE_KEY)
        response.delete_cookie(key = "redirect_to")
        return response

    response = RedirectResponse("/", status_code=302)
    db.delete_session(session_token)
    response.delete_cookie(key=COOKIE_KEY)
    return response


@router.get("/saml/metadata", summary="SAML 2.0 SP metadata", include_in_schema=False)
def saml_metadata(request: Request, db=Depends(get_db)):
    """Communicates the service provider metadata for SAML 2.0."""
    accept = request.headers.get("Accept")
    if not (accepts_content_type(accept, "application/samlmetadata+xml", strict=False) or
            accepts_xml(accept)):
        return errors.error_406("text/xml")

    if config.identity_provider != "saml":
        return errors.error_404(db, request)

    try:
        from xmlsec import Error as xmlsecError  # pylint: disable=import-outside-toplevel
    except (ImportError, ModuleNotFoundError):
        return errors.error_500("SAML support is not available.")

    try:
        http_fields = saml_service.request_to_saml_request(
            request.url.path, dict(request.query_params), {})
        metadata, validation_errors = saml_service.sp_metadata(http_fields)
        if len(validation_errors) == 0:
            return Response(content=metadata, media_type="text/xml")

        _log.error("SAML SP Metadata validation failed.")
        _log.error("Errors: %s", ", ".join(validation_errors))
    except xmlsecError as error:
        _log.error("SAML configuration error: %s", error)

    return errors.error_500()
