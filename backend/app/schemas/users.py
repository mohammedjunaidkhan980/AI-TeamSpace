from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator


class UserProfileUpdate(BaseModel):
    username: str | None = Field(
        default=None,
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-z0-9_]+$",
    )
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    profile_picture_url: HttpUrl | None = None
    bio: str | None = Field(default=None, max_length=500)
    status_message: str | None = Field(default=None, max_length=100)

    model_config = ConfigDict(extra="forbid")

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else value

    @field_validator("full_name")
    @classmethod
    def trim_full_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Full name cannot be null")
        value = value.strip()
        if not value:
            raise ValueError("Full name cannot be blank")
        return value

    @field_validator("username")
    @classmethod
    def require_username_value(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("Username cannot be null")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "UserProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one profile field must be provided")
        return self


class UserProfileResponse(BaseModel):
    id: str
    username: str
    full_name: str
    email: EmailStr
    profile_picture_url: HttpUrl | None = None
    bio: str | None = None
    status_message: str | None = None
    created_at: datetime


class PublicUserProfile(BaseModel):
    id: str
    username: str
    full_name: str
    profile_picture_url: HttpUrl | None = None
    bio: str | None = None
    status_message: str | None = None
    created_at: datetime


class UserSearchResponse(BaseModel):
    items: list[PublicUserProfile]
    limit: int
    offset: int
