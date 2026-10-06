"""Shared schema helpers."""

from __future__ import annotations

import re
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from tourdesk.core.text import clean_text, safe_url

T = TypeVar("T")

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s.]{2,}$")
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    offset: int = 0
    limit: int = 50


class OkResponse(ApiModel):
    ok: bool = True
    detail: str | None = None


def _username(value: str) -> str:
    value = value.strip()
    if not USERNAME_RE.match(value):
        raise ValueError(
            "Benutzername: 3–32 Zeichen, Buchstaben, Ziffern, Punkt, Binde- und Unterstrich; "
            "muss mit Buchstabe oder Ziffer beginnen."
        )
    return value


def _email(value: str) -> str:
    value = value.strip()
    if len(value) > 254 or not EMAIL_RE.match(value):
        raise ValueError("Bitte eine gültige E-Mail-Adresse angeben.")
    return value


def _url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    url = value.strip()
    if "://" not in url:
        url = "https://" + url
    checked = safe_url(url, max_length=500)
    if checked is None:
        raise ValueError("Bitte eine gültige http(s)-URL angeben.")
    return checked


def _text(value: str | None) -> str | None:
    return clean_text(value)


Username = Annotated[str, Field(min_length=3, max_length=32), AfterValidator(_username)]
Email = Annotated[str, Field(min_length=3, max_length=254), AfterValidator(_email)]
HttpUrl = Annotated[str | None, AfterValidator(_url)]
CleanStr = Annotated[str | None, AfterValidator(_text)]
