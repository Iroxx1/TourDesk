"""Audit logging for security relevant and administrative actions."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from tourdesk.models import AuditLog, User

audit_log = logging.getLogger("tourdesk.audit")
auth_log = logging.getLogger("tourdesk.auth")


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    actor_username: str | None = None,
    request: Request | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    target_label: str | None = None,
    success: bool = True,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    ip = request.client.host if request is not None and request.client else None
    ua = request.headers.get("user-agent") if request is not None else None
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_username=actor.username if actor else actor_username,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        target_label=target_label,
        success=success,
        details=details or {},
        ip=ip,
        user_agent=(ua or "")[:400] or None,
    )
    db.add(entry)
    logger = auth_log if action.startswith("auth.") else audit_log
    logger.info(
        action,
        extra={
            "event": action,
            "actor": entry.actor_username,
            "target_type": target_type,
            "target_id": entry.target_id,
            "success": success,
            "client_ip": ip,
        },
    )
    return entry
