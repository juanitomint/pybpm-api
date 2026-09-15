"""Pydantic schemas for User, Group, and Profile management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    nick: str = Field(..., min_length=1, max_length=255)
    name: str | None = Field(None, max_length=128)
    lastname: str | None = Field(None, max_length=128)
    email: str | None = Field(None, max_length=255)
    idgroup: int | None = None
    notification_by_email: str | None = Field(None, pattern="^(yes|no)$")


class UserUpdate(BaseModel):
    name: str | None = None
    lastname: str | None = None
    email: str | None = None
    idgroup: int | None = None
    notification_by_email: str | None = Field(None, pattern="^(yes|no)$")


class UserRead(BaseModel):
    idu: int
    nick: str
    name: str | None
    lastname: str | None
    email: str | None
    idgroup: int | None
    last_acc: datetime | None
    notification_by_email: str | None
    signature: str | None
    perm: list | None

    model_config = ConfigDict(from_attributes=True)


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    desc: str | None = None
    idsup: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    desc: str | None = None
    idsup: str | None = None


class GroupRead(BaseModel):
    idgroup: int
    name: str
    desc: str | None
    idsup: str | None

    model_config = ConfigDict(from_attributes=True)


class ProfileUpdate(BaseModel):
    name: str | None = None
    lastname: str | None = None
    email: str | None = None
    signature: str | None = None
    notification_by_email: str | None = None
