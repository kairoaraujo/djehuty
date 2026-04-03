"""Models for private link endpoints."""

from pydantic import BaseModel, Field


class PrivateLink(BaseModel):
    """A private sharing link for a dataset or collection."""
    id: str | None = Field(None, description="Link identifier string")
    is_active: bool = True
    expires_date: str | None = Field(None, description="Expiration date (ISO 8601), or null for no expiry")


class PrivateLinkInput(BaseModel):
    """Input for creating/updating a private link."""
    expires_date: str | None = Field(None, max_length=32, description="ISO 8601 date for expiry")
