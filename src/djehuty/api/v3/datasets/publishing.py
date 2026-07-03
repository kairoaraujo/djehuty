"""Dataset review and publication endpoints for the v3 API."""

from fastapi import APIRouter, Body, Depends, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, require_auth, resolve_reviewer_context
from djehuty.api.exceptions import ForbiddenError, InvalidInputError
from djehuty.api.models.common import ErrorResponse
from djehuty.api.v3._shared import _ok
from djehuty.api.v3.datasets._shared import _resolve_dataset
from djehuty.web.config import config

router = APIRouter(tags=["V3 / Datasets / Publishing"])

_LOCATION_EXAMPLE = {
    "location": "https://data.4tu.nl/published/27e6a01d-3f09-4d90-ae02-1d749ae9efb8"
}


@router.put(
    "/datasets/{dataset_id}/submit-for-review",
    summary="Submit dataset for review",
    description=(
        "Submit a draft dataset for curator review before publication. "
        "Performs metadata validation, persists the supplied metadata "
        "(``db.update_dataset``), and registers a review record "
        "(``db.insert_review``)."
    ),
    responses={204: {"description": "Submitted for review"}, 403: {"model": ErrorResponse}},
)
def submit_for_review(
    dataset_id: str,
    body: dict = Body(
        ...,
        openapi_examples={
            "dataset": {
                "summary": "Submit an open dataset",
                "value": {
                    "title": "Coastal water temperature measurements",
                    "description": "<p>Hourly measurements collected in 2025.</p>",
                    "defined_type": "dataset",
                    "is_embargoed": False,
                    "is_metadata_record": False,
                    "agreed_to_deposit_agreement": True,
                    "agreed_to_publish": True,
                    "categories": ["a9f8d3c1-2b4e-4c6a-8d1f-3e5b7c9a0d2f"],
                    "group_id": 28586,
                    "license_id": 2,
                    "publisher": "4TU.ResearchData",
                    "language": "en",
                },
            }
        },
    ),
    account=Depends(require_auth),
    db=Depends(get_db),
):
    from djehuty.utils.convenience import normalize_doi, value_or, value_or_none
    from djehuty.web import validator

    if not isinstance(body, dict):
        raise InvalidInputError("Request body must be a JSON object.", "BadBody")

    account_uuid = account["uuid"]
    dataset = _resolve_dataset(db, dataset_id, account_uuid)

    if value_or(dataset, "is_shared_with_me", False):
        raise ForbiddenError("Collaborators cannot submit a dataset for review.")

    try:
        dataset_type = validator.string_value(body, "defined_type", 0, 16)
        defined_type = 0
        if dataset_type == "software":
            defined_type = 9
        elif dataset_type == "dataset":
            defined_type = 3

        errors: list = []
        is_embargoed = validator.boolean_value(body, "is_embargoed", when_none=False)
        embargo_options = validator.array_value(body, "embargo_options")
        embargo_option = value_or_none(embargo_options, 0)
        is_restricted = value_or(embargo_option, "id", 0) == 1000
        is_closed = value_or(embargo_option, "id", 0) == 1001
        is_temporary_embargo = is_embargoed and not is_restricted and not is_closed
        agreed_to_deposit_agreement = validator.boolean_value(
            body, "agreed_to_deposit_agreement", True, False, errors
        )
        agreed_to_publish = validator.boolean_value(body, "agreed_to_publish", True, False, errors)

        if is_restricted or is_closed:
            body["embargo_type"] = "file"

        if not agreed_to_deposit_agreement:
            errors.append(
                {
                    "field_name": "agreed_to_deposit_agreement",
                    "message": "The dataset cannot be published without agreeing to the Deposit Agreement.",
                }
            )

        if not agreed_to_publish:
            errors.append(
                {
                    "field_name": "agreed_to_publish",
                    "message": "The dataset cannot be published without giving the reviewer permission to do so.",
                }
            )

        authors = db.authors(item_uri=dataset["uri"], item_type="dataset")
        if not authors:
            errors.append(
                {
                    "field_name": "authors",
                    "message": "The dataset must have at least one author.",
                }
            )

        tags = db.tags(item_uri=dataset["uri"], account_uuid=account_uuid)
        if not tags:
            errors.append(
                {
                    "field_name": "tag",
                    "message": "The dataset must have at least one keyword.",
                }
            )

        categories = db.categories(
            item_uri=dataset["uri"],
            account_uuid=account_uuid,
            is_published=False,
            limit=None,
        )
        if not categories:
            errors.append(
                {
                    "field_name": "categories",
                    "message": "Please specify at least one category.",
                }
            )

        resource_doi = normalize_doi(validator.string_value(body, "resource_doi", 0, 255, False))
        if not validator.is_valid_doi(resource_doi):
            errors.append(
                {
                    "field_name": "resource_doi",
                    "message": "Please enter a valid DOI.",
                }
            )

        codecheck_certificate_doi = normalize_doi(
            validator.string_value(body, "codecheck_certificate_doi", 0, 255, False)
        )
        if not validator.is_valid_doi(codecheck_certificate_doi):
            errors.append(
                {
                    "field_name": "codecheck_certificate_doi",
                    "message": "Please enter a valid DOI.",
                }
            )

        license_id = validator.integer_value(body, "license_id", 0, pow(2, 63), True, errors)
        license_url = db.license_url_by_id(license_id) if license_id else None

        parameters = {
            "dataset_uuid": dataset["uuid"],
            "account_uuid": account_uuid,
            "title": validator.string_value(body, "title", 3, 1000, True, errors),
            "description": validator.string_value(
                body, "description", 0, 10000, True, errors, strip_html=False
            ),
            "resource_doi": resource_doi,
            "resource_title": validator.string_value(body, "resource_title", 0, 255, False, errors),
            "license_url": license_url,
            "group_id": validator.integer_value(body, "group_id", 0, pow(2, 63), True, errors),
            "time_coverage": validator.string_value(body, "time_coverage", 0, 512, False, errors),
            "publisher": validator.string_value(body, "publisher", 0, 10000, True, errors),
            "language": validator.string_value(body, "language", 0, 10, True, errors),
            "contributors": validator.string_value(body, "contributors", 0, 10000, False, errors),
            "license_remarks": validator.string_value(
                body, "license_remarks", 0, 10000, False, errors
            ),
            "geolocation": validator.string_value(body, "geolocation", 0, 255, False, errors),
            "longitude": validator.string_value(body, "longitude", 0, 64, False, errors),
            "latitude": validator.string_value(body, "latitude", 0, 64, False, errors),
            "mimetype": validator.string_value(body, "format", 0, 512, False, errors),
            "data_link": validator.string_value(body, "data_link", 0, 255, False, errors),
            "derived_from": validator.string_value(body, "derived_from", 0, 255, False, errors),
            "same_as": validator.string_value(body, "same_as", 0, 255, False, errors),
            "organizations": validator.string_value(body, "organizations", 0, 2048, False, errors),
            "is_embargoed": is_embargoed,
            "is_restricted": is_restricted,
            "is_metadata_record": validator.boolean_value(
                body, "is_metadata_record", when_none=False
            ),
            "metadata_reason": validator.string_value(
                body, "metadata_reason", 0, 512, strip_html=False
            ),
            "embargo_until_date": validator.date_value(
                body, "embargo_until_date", is_temporary_embargo, errors
            ),
            "embargo_type": validator.options_value(
                body, "embargo_type", validator.embargo_types, is_temporary_embargo, errors
            ),
            "embargo_title": validator.string_value(
                body, "embargo_title", 0, 1000, is_embargoed, errors
            ),
            "embargo_reason": validator.string_value(
                body, "embargo_reason", 0, 10000, is_embargoed, errors, strip_html=False
            ),
            "eula": validator.string_value(
                body, "eula", 0, 50000, is_restricted, errors, strip_html=False
            ),
            "defined_type_name": dataset_type,
            "defined_type": defined_type,
            "agreed_to_deposit_agreement": agreed_to_deposit_agreement,
            "agreed_to_publish": agreed_to_publish,
            "categories": validator.array_value(body, "categories", True, errors),
            "requested_codecheck": validator.boolean_value(
                body, "requested_codecheck", False, False
            ),
            "codecheck_certificate_doi": codecheck_certificate_doi,
        }

        if not parameters["is_metadata_record"]:
            files = db.dataset_files(
                account_uuid=account_uuid,
                dataset_uri=dataset["uri"],
                limit=1,
            )
            if not files and parameters["defined_type_name"] != "software":
                errors.append(
                    {
                        "field_name": "files",
                        "message": "Upload at least one file, or choose metadata-only record.",
                    }
                )

        if errors:
            raise InvalidInputError(errors, "ValidationFailed")

        account_record = db.account_by_uuid(dataset["account_uuid"])
        if not account_record:
            raise InvalidInputError("Dataset owner account not found.", "AccountMissing")

        # Guard the submit flow with the same process-level lock the legacy
        # uses, so concurrent submits cannot race on review-record creation.
        from djehuty.services import email as email_module
        from djehuty.web.locks import Locks, LockTypes

        process_locks = Locks()
        process_locks.lock(LockTypes.SUBMIT_DATASET)
        try:
            if not db.update_dataset(**parameters):
                raise InvalidInputError("Failed to persist dataset metadata.", "UpdateFailed")

            if db.insert_review(dataset["uri"]) is None:
                raise InvalidInputError("Failed to register review record.", "InsertReviewFailed")
        finally:
            process_locks.unlock(LockTypes.SUBMIT_DATASET)

        # Side-effect notifications. Failures are logged but never affect the
        # HTTP response (mirrors legacy behaviour).
        subject = f"Request for review: {dataset['container_uuid']}"
        email_module.send_email_to_reviewers(
            db,
            subject,
            "submitted_for_review_notification",
            account_email=value_or_none(account_record, "email"),
            dataset=dataset,
            account=account_record,
        )

        if config.in_production and not config.in_preproduction and account_record.get("email"):
            email_module.send_templated_email(
                db,
                [account_record["email"]],
                f"Submission of {dataset['title']}.",
                "dataset_submitted",
                dataset=dataset,
                account=account_record,
                support_email=config.support_email_address,
                site_name=config.site_name,
            )

        return Response(status_code=204)

    except validator.ValidationException as error:
        raise InvalidInputError(error.message, error.code)


@router.post(
    "/datasets/{dataset_id}/publish",
    summary="Publish a dataset",
    description=(
        "Publish a draft dataset. Requires reviewer permissions on the "
        "calling account. The production DataCite DOI reservation flow is "
        "gated by ``config.in_production`` and skipped in dev/preproduction."
    ),
    responses={201: _ok("Dataset published", _LOCATION_EXAMPLE), 403: {"model": ErrorResponse}},
)
def publish_dataset(
    dataset_id: str,
    account=Depends(require_auth),
    reviewer=Depends(resolve_reviewer_context),
    db=Depends(get_db),
):
    # ``account`` is resolved from the regular session cookie (the
    # dataset's owner — the impersonated depositor when the reviewer
    # invoked /review/goto-dataset/<id> first).
    # ``reviewer`` is resolved from the impersonator cookie when present,
    # otherwise from the same session as ``account``; in both cases it is
    # guaranteed to have reviewer permissions.
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])

    if (
        reviewer["may_review_institution"]
        and not reviewer["may_review_all"]
        and reviewer["account"].get("group_id") != dataset.get("group_id")
    ):
        raise ForbiddenError("Reviewer group mismatch.")

    from djehuty.services import email as email_module
    from djehuty.utils.convenience import value_or_none

    reviewer_account = reviewer["account"]

    review_uri = dataset.get("review_uri")
    if review_uri:
        db.update_review(
            review_uri,
            author_account_uuid=dataset["account_uuid"],
            assigned_to=reviewer_account.get("uuid"),
            status="assigned",
        )

    container_uuid = dataset["container_uuid"]

    # DOI reservation is production-only and needs the DataCite helpers that
    # still live on the legacy server. Until they are extracted, production
    # deployments must keep the publish endpoint on the legacy stack.
    if config.in_production and not config.in_preproduction:
        raise InvalidInputError(
            "Publishing via the FastAPI implementation is not yet wired up "
            "for production DOI reservation.",
            "PublishUnavailableInProd",
        )

    if not db.publish_dataset(container_uuid, account["uuid"]):
        raise InvalidInputError("Failed to publish dataset.", "PublishFailed")

    # Re-fetch the dataset so we get the freshly assigned DOIs.
    try:
        dataset = db.datasets(dataset_uuid=dataset["uuid"], use_cache=False)[0]
    except (IndexError, AttributeError):
        dataset = dataset  # fall back to the pre-publish copy

    # Send the approval e-mail to the depositor. Best-effort; logged on
    # failure but does not block the publication response.
    try:
        owner = db.account_by_uuid(dataset["account_uuid"])
        if owner and owner.get("email"):
            subject = f"Approved: {dataset['title']}"
            email_module.send_templated_email(
                db,
                [owner["email"]],
                subject,
                "dataset_approved",
                base_url=config.base_url,
                support_email=config.support_email_address,
                title=dataset["title"],
                container_uuid=container_uuid,
                versioned_doi=value_or_none(dataset, "doi"),
                container_doi=dataset.get("container_doi"),
            )
    except (KeyError, AttributeError, IndexError):
        # Email side effects must never prevent publication.
        pass

    return JSONResponse(
        content={"location": f"{config.base_url}/published/{dataset_id}"},
        status_code=201,
    )


@router.post(
    "/datasets/{dataset_id}/decline",
    summary="Decline a dataset (reviewer)",
    description="Decline a dataset that was submitted for review. Requires reviewer privileges.",
    responses={
        201: _ok(
            "Dataset declined",
            {"location": "https://data.4tu.nl/review/overview"},
        ),
        403: {"model": ErrorResponse},
    },
)
def decline_dataset(
    dataset_id: str,
    account=Depends(require_auth),
    reviewer=Depends(resolve_reviewer_context),
    db=Depends(get_db),
):
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])

    if (
        reviewer["may_review_institution"]
        and not reviewer["may_review_all"]
        and reviewer["account"].get("group_id") != dataset.get("group_id")
    ):
        raise ForbiddenError("Reviewer group mismatch.")

    from djehuty.services import email as email_module
    from djehuty.utils.convenience import value_or_none

    if not db.decline_dataset(dataset["container_uuid"], account["uuid"]):
        raise InvalidInputError("Failed to decline dataset.", "DeclineFailed")

    # Notify the depositor and the reviewer pool. Best-effort; logged on
    # failure but does not block the decline response.
    try:
        owner = db.account_by_uuid(dataset["account_uuid"])
        if owner:
            subject = f"Declined: {dataset['title']}"
            parameters = {
                "base_url": config.base_url,
                "support_email": config.support_email_address,
                "title": dataset["title"],
            }
            if owner.get("email"):
                email_module.send_templated_email(
                    db,
                    [owner["email"]],
                    subject,
                    "dataset_declined",
                    **parameters,
                )
            email_module.send_email_to_reviewers(
                db,
                subject,
                "declined_dataset_notification",
                account_email=value_or_none(owner, "email"),
                dataset=dataset,
                **parameters,
            )
    except (KeyError, AttributeError, IndexError):
        pass

    return JSONResponse(
        content={"location": f"{config.base_url}/review/overview"},
        status_code=201,
    )
