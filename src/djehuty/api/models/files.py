"""Models for file endpoints."""

from pydantic import BaseModel, Field


class FileSummary(BaseModel):
    """File record as returned in article file listings."""
    id: int | None = None
    uuid: str | None = None
    name: str | None = Field(None, examples=["measurements.csv"])
    size: int | None = Field(None, description="File size in bytes")
    is_link_only: bool = False
    download_url: str | None = None
    supplied_md5: str | None = None
    computed_md5: str | None = None
    status: str | None = None


class FileDetail(BaseModel):
    """Detailed file record."""
    id: int | None = None
    uuid: str | None = None
    name: str | None = None
    size: int | None = None
    is_link_only: bool = False
    download_url: str | None = None
    supplied_md5: str | None = None
    computed_md5: str | None = None
    status: str | None = None
    viewer_type: str | None = None
    preview_state: str | None = None
    upload_url: str | None = None
    upload_token: str | None = None
