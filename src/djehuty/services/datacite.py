"""
Shared DataCite DOI helpers.

Extracted from ``djehuty.web.wsgi`` so the FastAPI publish / decline /
reserve-DOI handlers can register and update DOIs identically to the
legacy implementation. All public functions are stateless except for
their ``db`` argument; they read configuration directly from
:mod:`djehuty.web.config`.
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import date

import requests

from djehuty.utils.convenience import (
    decimal_coords,
    landing_page_url,
    parses_to_int,
    self_or_value_or_none,
    value_or,
    value_or_none,
)
from djehuty.web import validator, xml_formatter
from djehuty.web.config import config


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DOI computation + reservation
# ---------------------------------------------------------------------------

def standard_doi(
    container_uuid: str,
    version: int | None = None,
    container_doi: str | None = None,
) -> str:
    """Return the canonical DOI for ``container_uuid`` (and optional version).

    Mirrors :func:`djehuty.web.wsgi.ApiServer.__standard_doi`.
    """
    if not container_doi:
        container_doi = f"{config.datacite_prefix}/{container_uuid}"
    doi = container_doi
    if version:
        doi += f".v{version}"
    return doi


def datacite_reserve_doi(doi: str | None = None) -> dict | None:
    """Reserve ``doi`` at DataCite, or a new DOI under the configured prefix.

    Returns the DataCite JSON response for HTTP 201 (new reservation) or
    HTTP 422 (already-reserved). Returns ``None`` on any other error.
    """
    headers = {
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }
    attributes = {"doi": doi} if doi else {"prefix": config.datacite_prefix}
    json_data = {"data": {"type": "dois", "attributes": attributes}}

    try:
        response = requests.post(
            f"{config.datacite_url}/dois",
            headers=headers,
            auth=(config.datacite_id, config.datacite_password),
            timeout=60,
            json=json_data,
        )
        if response.status_code in (201, 422):
            return response.json()
        _log.error(
            "DataCite responded with %s (%s)",
            response.status_code,
            response.text,
        )
    except requests.exceptions.ConnectionError:
        _log.error("Failed to reserve a DOI due to a connection error.")

    return None


def reserve_and_save_doi(
    db,
    account_uuid: str,
    item: dict,
    version: int | None = None,
    item_type: str = "dataset",
) -> str | bool:
    """Reserve the canonical DOI for ``item`` and persist it.

    Returns the reserved DOI on success or ``False`` on any failure.
    If the DOI is already reserved at DataCite, returns the existing
    DOI (matches the legacy idempotent behaviour).
    """
    if item is None or account_uuid is None:
        return False

    container_uuid = item["container_uuid"]
    doi = standard_doi(
        container_uuid, version, value_or_none(item, "container_doi")
    )
    if doi.split("/")[0] != config.datacite_prefix:
        _log.error("Doi %s of %s has wrong prefix", doi, container_uuid)
        return False

    data = datacite_reserve_doi(doi)
    if value_or_none(data, "errors"):  # already reserved
        return doi
    if data is None:
        return False

    try:
        doi_type = "doi" if version else "container_doi"
        more_parm = {
            doi_type: doi,
            "is_first_online": "timeline_first_online" not in item,
        }
        if item_type == "dataset":
            if db.update_dataset(
                item["uuid"],
                account_uuid,
                time_coverage=value_or_none(item, "time_coverage"),
                publisher=value_or_none(item, "publisher"),
                mimetype=value_or_none(item, "format"),
                contributors=value_or_none(item, "contributors"),
                geolocation=value_or_none(item, "geolocation"),
                longitude=value_or_none(item, "longitude"),
                latitude=value_or_none(item, "latitude"),
                data_link=value_or_none(item, "data_link"),
                same_as=value_or_none(item, "same_as"),
                organizations=value_or_none(item, "organizations"),
                resource_title=value_or_none(item, "resource_title"),
                resource_doi=value_or_none(item, "resource_doi"),
                embargo_until_date=value_or_none(item, "embargo_until_date"),
                agreed_to_deposit_agreement=value_or(
                    item, "agreed_to_deposit_agreement", False
                ),
                agreed_to_publish=value_or(item, "agreed_to_publish", False),
                is_metadata_record=value_or(item, "is_metadata_record", False),
                is_embargoed=value_or(item, "is_embargoed", False),
                is_restricted=value_or(item, "is_restricted", False),
                categories=None,
                **more_parm,
            ):
                return doi
        else:
            if db.update_collection(item["uuid"], account_uuid, **more_parm):
                return doi
    except KeyError:
        pass

    _log.error(
        "Updating the %s %s for reserving DOI %s failed.",
        item_type,
        item["container_uuid"],
        doi,
    )
    return False


# ---------------------------------------------------------------------------
# DOI metadata update (PUT to DataCite with full XML payload)
# ---------------------------------------------------------------------------

def _parse_organizations(text: str) -> list[str]:
    return [x for x in re.split(r"\s*[;\n]\s*", text) if x != ""]


def _parse_contributors(text: str) -> list[dict]:
    contributors: list[dict] = []
    for contributor in text.split(";\n"):
        if not contributor:
            continue
        parts = contributor.split(" [orcid:", 1)
        record = {"name": parts[0]}
        if parts[1:]:
            record["orcid"] = parts[1][:-1]
        contributors.append(record)
    return contributors


def metadata_export_parameters(
    db,
    item_id,
    version: int | None = None,
    item_type: str = "dataset",
    from_draft: bool = False,
) -> dict | None:
    """Collect the parameter dict required to render DataCite XML."""
    container_uuid = item_id
    if parses_to_int(item_id):
        container_uuid = db.container_uuid_by_id(item_id)
    elif not validator.is_valid_uuid(item_id):
        return None

    is_dataset = item_type == "dataset"
    items_function = db.datasets if is_dataset else db.collections
    container = db.container(
        container_uuid, item_type=item_type, use_cache=bool(version)
    )

    current_version = version
    if not version:
        current_version = value_or(container, "latest_published_version_number", 0)
        if from_draft:
            current_version += 1

    item = None
    published_date = None
    if from_draft:
        try:
            item = items_function(
                container_uuid=container_uuid, is_published=False
            )[0]
            item["version"] = current_version
        except IndexError:
            _log.warning("No draft for %s.", item_id)
        published_date = date.today().isoformat()
    else:
        try:
            item = items_function(
                container_uuid=container_uuid,
                version=current_version,
                is_published=True,
            )[0]
            if item is not None and "published_date" in item:
                published_date = item["published_date"][:10]
        except IndexError:
            _log.warning(
                "Nothing found for %s %s version %s.",
                item_type, item_id, current_version,
            )

    if item is None:
        return None

    item_uuid = item["uuid"]
    item_uri = f"{item_type}:{item_uuid}"
    lat = self_or_value_or_none(item, "latitude")
    lon = self_or_value_or_none(item, "longitude")
    lat_valid, lon_valid = decimal_coords(lat, lon)

    doi = value_or_none(item, "doi")
    if not bool(doi):
        doi = standard_doi(
            container_uuid, version, value_or_none(container, "doi")
        )
        _log.info("Using predicted DOI (%s) for %s.", doi, item_uri)

    parameters: dict = {
        "item": item,
        "container_doi": value_or_none(container, "doi"),
        "doi": doi,
        "authors": db.authors(item_uri=item_uri, item_type=item_type),
        "categories": db.categories(item_uri=item_uri, limit=None),
        "tags": [t["tag"] for t in db.tags(item_uri=item_uri)],
        "published_year": published_date[:4] if published_date else None,
        "published_date": published_date,
        "organizations": _parse_organizations(
            value_or(item, "organizations", "")
        ),
        "contributors": _parse_contributors(value_or(item, "contributors", "")),
        "references": db.references(item_uri=item_uri, limit=None),
        "coordinates": {"lat_valid": lat_valid, "lon_valid": lon_valid},
    }
    if is_dataset:
        parameters["fundings"] = db.fundings(item_uri=item_uri)
    return parameters


def update_item_doi(
    db,
    item_id,
    version: int | None = None,
    item_type: str = "dataset",
    from_draft: bool = True,
) -> bool:
    """Update the metadata of an existing DOI at DataCite.

    Returns ``True`` on success (HTTP 200 or 201), ``False`` on any
    other status or connection error.
    """
    parameters = metadata_export_parameters(
        db, item_id, version, item_type=item_type, from_draft=from_draft
    )
    if parameters is None:
        return False

    xml_bytes = xml_formatter.datacite(parameters, indent=False)
    xml = str(xml_bytes, encoding="utf-8")
    # DataCite rejects the XML declaration unless it's encoded a specific way.
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + xml.split("?>", 1)[1]
    doi = parameters["doi"]
    encoded = base64.b64encode(xml.encode("utf-8"))

    headers = {
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }
    json_data = {
        "data": {
            "attributes": {
                "event": "publish",  # idempotent when already published
                "url": landing_page_url(
                    item_id, version, item_type=item_type,
                    base_url=config.base_url,
                ),
                "xml": str(encoded, "utf-8"),
            }
        }
    }

    try:
        response = requests.put(
            f"{config.datacite_url}/dois/{doi}",
            headers=headers,
            auth=(config.datacite_id, config.datacite_password),
            timeout=60,
            json=json_data,
        )
        if response.status_code == 201:
            return True
        if response.status_code == 200:
            _log.warning("Doi %s already active, updated", doi)
            return True
        _log.error(
            "DataCite responded with %s (%s)",
            response.status_code,
            response.text,
        )
    except requests.exceptions.ConnectionError:
        _log.error("Failed to update a DOI due to a connection error.")

    return False
