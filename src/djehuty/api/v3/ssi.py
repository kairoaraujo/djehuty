"""SSI intake endpoints for the v3 API."""

from fastapi import APIRouter, Body, Depends

from djehuty.api.dependencies import get_db
from djehuty.api.exceptions import ForbiddenError, NotFoundError
from djehuty.web.config import config

router = APIRouter(tags=["V3 / SSI"])


@router.put(
    "/receive-from-ssi",
    summary="Receive dataset from SSI",
    responses={302: {"description": "Redirect to the newly created draft dataset editor"}},
)
def receive_from_ssi(
    body: dict = Body(
        ...,
        openapi_examples={
            "default": {
                "summary": "Create a draft from an SSI hand-off",
                "value": {
                    "psk": "shared-pre-shared-key",
                    "title": "Coastal water temperature measurements",
                    "email": "researcher@example.org",
                },
            }
        },
    ),
    db=Depends(get_db),
):
    import hmac

    from djehuty.web import validator

    if config.ssi_psk is None:
        raise NotFoundError()

    psk = body.get("psk", "")
    if not hmac.compare_digest(str(psk), config.ssi_psk):
        raise ForbiddenError()

    title = validator.string_value(body, "title", 0, 255, True)
    email = validator.string_value(body, "email", 0, 255, True)

    acct = db.account_by_email(email)
    account_uuid = acct["uuid"] if acct else db.insert_account(email=email)

    token, _, session_uuid = db.insert_session(account_uuid, name="Login via SSI")
    container_uuid, _ = db.insert_dataset(title=title, account_uuid=account_uuid)

    from fastapi.responses import RedirectResponse

    return RedirectResponse(
        url=f"{config.base_url}/v3/redirect-from-ssi/{container_uuid}/{token}",
        status_code=302,
    )


@router.get(
    "/redirect-from-ssi/{container_uuid}/{token}",
    summary="Complete SSI redirect",
    responses={302: {"description": "Set the session cookie and redirect to the dataset editor"}},
)
def redirect_from_ssi(container_uuid: str, token: str):
    from djehuty.web import validator

    if not validator.is_valid_uuid(container_uuid):
        raise ForbiddenError()

    from fastapi.responses import RedirectResponse

    response = RedirectResponse(url=f"/my/datasets/{container_uuid}/edit", status_code=302)
    response.set_cookie(
        key="djehuty_session",
        value=token,
        secure=config.in_production,
        httponly=True,
        samesite="lax",
    )
    return response
