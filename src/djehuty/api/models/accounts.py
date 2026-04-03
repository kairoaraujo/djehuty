"""Models for account and institution endpoints."""

from pydantic import BaseModel, Field


class AccountSummary(BaseModel):
    """Account summary record."""
    id: int | None = None
    uuid: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    is_active: bool = False
    is_public: bool = False
    job_title: str | None = None
    orcid_id: str = ""


class AccountDetail(BaseModel):
    """Detailed account record (includes email)."""
    id: int | None = None
    uuid: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    email: str | None = None
    is_active: bool = False
    is_public: bool = False
    job_title: str | None = None
    orcid_id: str = ""
    quota: int | None = None
    used_quota: int | None = None
    institution_id: int | None = None
    group_id: int | None = None


class ProfileUpdate(BaseModel):
    """Input for updating profile."""
    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    job_title: str | None = Field(None, max_length=512)


class QuotaRequest(BaseModel):
    """Request for additional storage quota."""
    requested_size: int = Field(..., gt=0, description="Requested quota in bytes")
    reason: str = Field(..., max_length=10000, description="Reason for the request")
