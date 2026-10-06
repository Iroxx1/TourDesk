"""Schemas for countries, regions, cities, venues and filter profiles."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from tourdesk.schemas.common import ApiModel, CleanStr, HttpUrl


class CountryOut(ApiModel):
    id: int
    code: str
    name: str
    name_en: str
    priority: int
    region_count: int = 0


class RegionOut(ApiModel):
    id: int
    country_id: int
    country_code: str
    country_name: str
    code: str | None = None
    name: str
    local_name: str
    kind: str
    parent_id: int | None = None
    city_count: int | None = None


class CityOut(ApiModel):
    id: int
    name: str
    local_name: str
    country_id: int
    country_code: str
    country_name: str
    region_id: int | None = None
    region_name: str | None = None
    population: int = 0
    latitude: float | None = None
    longitude: float | None = None
    timezone: str | None = None
    is_auto: bool = False
    needs_review: bool = False


class CityCreate(ApiModel):
    name: str = Field(min_length=1, max_length=160)
    country_id: int
    region_id: int | None = None


class CityUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    region_id: int | None = None
    needs_review: bool | None = None


class VenueOut(ApiModel):
    id: int
    name: str
    aliases: list[str] = []
    city_id: int | None = None
    city_name: str | None = None
    region_id: int | None = None
    region_name: str | None = None
    country_id: int | None = None
    country_code: str | None = None
    country_name: str | None = None
    address: str | None = None
    postal_code: str | None = None
    website: str | None = None
    kind: str | None = None
    capacity: int | None = None
    is_auto: bool = False
    needs_review: bool = False
    upcoming_event_count: int | None = None
    has_agenda_source: bool = False
    is_favorite: bool = False


class VenueCreate(ApiModel):
    name: str = Field(min_length=2, max_length=200)
    city_id: int
    address: CleanStr = Field(default=None, max_length=300)
    postal_code: CleanStr = Field(default=None, max_length=20)
    website: HttpUrl = None
    agenda_url: HttpUrl = None
    aliases: list[str] = Field(default_factory=list, max_length=20)
    add_to_filters: bool = True


class VenueUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    city_id: int | None = None
    address: CleanStr = Field(default=None, max_length=300)
    postal_code: CleanStr = Field(default=None, max_length=20)
    website: HttpUrl = None
    aliases: list[str] | None = Field(default=None, max_length=30)
    kind: str | None = Field(default=None, max_length=32)
    needs_review: bool | None = None


LocationLevel = Literal["country", "region", "city", "venue"]


class LocationRuleOut(ApiModel):
    key: str
    level: LocationLevel
    target_id: int
    label: str
    context: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    description: str


class LocationRuleCreate(ApiModel):
    level: LocationLevel
    target_id: int


class FilterOut(ApiModel):
    id: int
    name: str
    date_mode: Literal["upcoming", "months", "range"]
    months_ahead: int | None = None
    date_from: date | None = None
    date_to: date | None = None
    include_concerts: bool
    include_support: bool
    include_special: bool
    festival_mode: Literal["artist", "always", "never"]
    festival_scope: Literal["filters", "anywhere"]
    show_cancelled: bool
    show_unconfirmed: bool
    default_show_festivals: bool
    locations: list[LocationRuleOut]


class FilterUpdate(ApiModel):
    date_mode: Literal["upcoming", "months", "range"] | None = None
    months_ahead: int | None = Field(default=None, ge=1, le=60)
    date_from: date | None = None
    date_to: date | None = None
    include_concerts: bool | None = None
    include_support: bool | None = None
    include_special: bool | None = None
    festival_mode: Literal["artist", "always", "never"] | None = None
    festival_scope: Literal["filters", "anywhere"] | None = None
    show_cancelled: bool | None = None
    show_unconfirmed: bool | None = None
    default_show_festivals: bool | None = None

    @model_validator(mode="after")
    def _range(self) -> FilterUpdate:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Das Startdatum muss vor dem Enddatum liegen.")
        return self
