"""Dataset collaborator endpoints for the v3 API."""

from fastapi import APIRouter, Body, Depends, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import InvalidInputError, NotFoundError
from djehuty.api.models.common import ErrorResponse
from djehuty.api.permissions import enforce_collaborative_permissions
from djehuty.api.v3._shared import _ok
from djehuty.web import formatter

router = APIRouter(tags=["V3 / Datasets / Collaborators"])

_COLLABORATOR_EXAMPLE = {
    "uuid": "5b8f2d1a-9c3e-4f7b-8a2d-1e6c4b9f0a3d",
    "account_uuid": "84cae99f-a691-4af2-9d21-f5c0817c26df",
    "first_name": "Dev",
    "last_name": "User",
    "email": "dev@djehuty.com",
    "metadata_read": True,
    "metadata_edit": True,
    "data_read": True,
    "data_edit": False,
    "data_remove": False,
    "is_supervisor": False,
    "group_id": 28586,
    "group_name": "Delft University of Technology",
    "is_inferred": False,
}


@router.get(
    "/datasets/{container_uuid}/collaborators",
    summary="List collaborators",
    responses={
        200: _ok("The dataset's collaborators", [_COLLABORATOR_EXAMPLE]),
        403: {"model": ErrorResponse},
    },
)
def list_collaborators(container_uuid: str, account=Depends(require_auth), db=Depends(get_db)):
    # First resolve the container to its dataset_uuid (which is what
    # db.collaborators expects).
    try:
        dataset = db.datasets(
            container_uuid=container_uuid,
            account_uuid=account["uuid"],
            is_published=None,
            is_latest=None,
            limit=1,
        )[0]
    except (IndexError, AttributeError):
        raise NotFoundError()

    enforce_collaborative_permissions(db, account["uuid"], dataset, "dataset", "metadata_read")

    collaborators = db.collaborators(dataset_uuid=dataset["uuid"], account_uuid=account["uuid"])
    return JSONResponse(content=[formatter.format_collaborator_record(c) for c in collaborators])


@router.put(
    "/datasets/{container_uuid}/collaborators/{collaborator_uuid}",
    summary="Add/update collaborator",
    responses={204: {"description": "Collaborator saved"}, 403: {"model": ErrorResponse}},
)
def update_collaborator(
    container_uuid: str,
    collaborator_uuid: str,
    body: dict = Body(
        ...,
        openapi_examples={
            "grant": {
                "summary": "Grant read/edit permissions",
                "value": {
                    "metadata_read": True,
                    "metadata_edit": True,
                    "data_read": True,
                    "data_edit": False,
                    "data_remove": False,
                },
            }
        },
    ),
    account=Depends(require_auth),
    db=Depends(get_db),
):
    if not isinstance(body, dict):
        raise InvalidInputError("Request body must be a JSON object.", "BadBody")
    try:
        dataset = db.datasets(
            container_uuid=container_uuid,
            account_uuid=account["uuid"],
            is_published=None,
            is_latest=None,
            limit=1,
        )[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
    enforce_collaborative_permissions(db, account["uuid"], dataset, "dataset", "metadata_edit")
    if not db.update_collaborator(
        container_uuid=container_uuid,
        collaborator_uuid=collaborator_uuid,
        account_uuid=account["uuid"],
        permissions=body,
    ):
        raise InvalidInputError("Failed to update collaborator.", "UpdateFailed")
    return Response(status_code=204)


@router.delete(
    "/datasets/{container_uuid}/collaborators/{collaborator_uuid}",
    summary="Remove collaborator",
    responses={204: {"description": "Collaborator removed"}, 403: {"model": ErrorResponse}},
)
def delete_collaborator(
    container_uuid: str, collaborator_uuid: str, account=Depends(require_auth), db=Depends(get_db)
):
    try:
        dataset = db.datasets(
            container_uuid=container_uuid,
            account_uuid=account["uuid"],
            is_published=None,
            is_latest=None,
            limit=1,
        )[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
    enforce_collaborative_permissions(db, account["uuid"], dataset, "dataset", "metadata_edit")
    db.delete_collaborator(container_uuid=container_uuid, collaborator_uuid=collaborator_uuid)
    return Response(status_code=204)
