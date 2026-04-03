"""Models for author endpoints."""

from pydantic import BaseModel, Field


class AuthorSummary(BaseModel):
    """Author as returned by list endpoints (v2 format)."""
    id: int | None = None
    uuid: str | None = None
    full_name: str | None = Field(None, examples=["Jane Doe"])
    is_active: bool = False
    url_name: str | None = None
    orcid_id: str = ""


class AuthorDetail(BaseModel):
    """Detailed author record."""
    id: int | None = None
    uuid: str | None = None
    first_name: str | None = Field(None, examples=["Jane"])
    last_name: str | None = Field(None, examples=["Doe"])
    full_name: str | None = Field(None, examples=["Jane Doe"])
    is_active: bool = False
    is_public: bool = False
    url_name: str | None = None
    orcid_id: str = ""
    job_title: str | None = None
    institution_id: int | None = None


class AuthorV3(BaseModel):
    """Author as returned by v3 endpoints."""
    uuid: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    email: str | None = None
    orcid: str | None = None
    is_editable: bool = False


class AuthorInput(BaseModel):
    """Input for adding/updating an author."""
    uuid: str | None = Field(None, description="UUID of an existing account")
    name: str | None = Field(None, max_length=255, description="Full name (for new external authors)")
    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    email: str | None = Field(None, max_length=255)
    orcid_id: str | None = Field(None, max_length=64)


class AuthorSearchRequest(BaseModel):
    """Request parameters for author search."""
    search: str | None = Field(None, max_length=255, description="Search term")
    limit: int | None = Field(None, ge=1, le=1000)
    offset: int | None = Field(None, ge=0)
