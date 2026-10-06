"""/api/settings – personal settings (design, wallpaper, dark mode, view, notifications)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from tourdesk.core.constants import ACCENT_COLORS, WALLPAPERS
from tourdesk.core.db import get_db
from tourdesk.core.timeutil import safe_zone
from tourdesk.models.enums import NOTIFICATION_LABELS
from tourdesk.models.user import DEFAULT_VIEW_SETTINGS
from tourdesk.schemas.users import SettingsOut, SettingsUpdate
from tourdesk.security.deps import AuthContext, get_context
from tourdesk.services.users import get_settings_row, settings_out

router = APIRouter(prefix="/settings", tags=["settings"])

_VIEW_ALLOWED = {
    "tile_size": {"small", "medium", "large"},
    "sort": {"next_event", "name", "added"},
}


@router.get("", response_model=SettingsOut)
def get_user_settings(ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)) -> SettingsOut:
    return settings_out(get_settings_row(db, ctx.user))


@router.put("", response_model=SettingsOut)
def update_user_settings(
    payload: SettingsUpdate, ctx: AuthContext = Depends(get_context), db: Session = Depends(get_db)
) -> SettingsOut:
    row = get_settings_row(db, ctx.user)
    data = payload.model_dump(exclude_unset=True)
    for key in ("theme", "wallpaper", "animations", "transparency"):
        if key in data and data[key] is not None:
            setattr(row, key, data[key])
    if "accent_color" in data:
        row.accent_color = data["accent_color"]
    if data.get("timezone") and safe_zone(data["timezone"]):
        row.timezone = data["timezone"]
    if data.get("view") is not None:
        view = dict(row.view or {})
        for key, value in data["view"].items():
            if key not in DEFAULT_VIEW_SETTINGS:
                continue
            allowed = _VIEW_ALLOWED.get(key)
            default = DEFAULT_VIEW_SETTINGS[key]
            if allowed is not None and value not in allowed:
                continue
            if isinstance(default, bool) and not isinstance(value, bool):
                continue
            if isinstance(default, int) and not isinstance(default, bool):
                if not isinstance(value, int) or not 1 <= value <= 10:
                    continue
            view[key] = value
        row.view = view
    if data.get("notifications") is not None:
        notif = dict(row.notifications or {})
        for key, value in data["notifications"].items():
            if key in NOTIFICATION_LABELS and isinstance(value, bool):
                notif[key] = value
        row.notifications = notif
    db.commit()
    return settings_out(row)


@router.get("/options")
def setting_options(ctx: AuthContext = Depends(get_context)) -> dict[str, Any]:
    return {
        "wallpapers": WALLPAPERS,
        "accent_colors": ACCENT_COLORS,
        "notification_types": [{"key": k, "name": v} for k, v in NOTIFICATION_LABELS.items()],
    }
