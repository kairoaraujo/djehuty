"""Models for funding endpoints."""

from pydantic import BaseModel, Field


class FundingRecord(BaseModel):
    """Funding record."""
    id: int | None = None
    uuid: str | None = None
    title: str | None = Field(None, examples=["NWO Open Science Fund"])
    funder_name: str | None = Field(None, examples=["NWO"])
    grant_code: str | None = Field(None, examples=["OSF-2025-001"])
    url: str | None = None
    is_user_defined: bool = False


class FundingInput(BaseModel):
    """Input for adding funding."""
    title: str | None = Field(None, max_length=1000)
    funder_name: str | None = Field(None, max_length=255)
    grant_code: str | None = Field(None, max_length=255)
    url: str | None = Field(None, max_length=1024)
    is_user_defined: int | None = Field(None, ge=0, le=1)


class FundingSearchRequest(BaseModel):
    """Request parameters for funding search."""
    search_for: str | None = Field(None, max_length=255)
    limit: int | None = Field(None, ge=1, le=1000)
    offset: int | None = Field(None, ge=0)
