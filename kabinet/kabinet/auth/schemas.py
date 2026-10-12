from enum import Enum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class Role(str, Enum):
    participant = 'participant'
    judge = 'judge'
    moderator = 'moderator'
    admin = 'admin'


class EmailInput(BaseModel):
    email: EmailStr

    @field_validator('email')
    @classmethod
    def normalize_email(cls, value):
        return str(value).strip().lower()


class Login(EmailInput):
    password: str = Field(min_length=1, max_length=1024)


class SetPassword(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=12, max_length=128)


class UserView(BaseModel):
    id: UUID
    email: str | None
    display_name: str | None
    full_name: str | None
    city: str | None = None
    account_status: str
    roles: list[Role]


class SessionView(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    expires_in: int


class ImportUser(BaseModel):
    telegram_id: int = Field(gt=0)
    full_name: str | None = Field(default=None, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)


class RoleChange(BaseModel):
    role: Role
    enabled: bool
