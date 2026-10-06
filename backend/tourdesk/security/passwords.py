"""Password hashing (Argon2id) and password policy."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from tourdesk.core.config import get_settings

# RFC 9106 "second recommended option": Argon2id, t=3, m=64 MiB, p=4
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4, hash_len=32, salt_len=16)
_DUMMY_HASH = _hasher.hash("tourdesk-dummy-password-for-timing")

_COMMON_PASSWORDS = {
    "password", "passwort", "password1", "password123", "passwort123", "123456789", "1234567890",
    "12345678910", "qwertzuiop", "qwertyuiop", "letmein123", "iloveyou12", "tourdesk", "tourdesk123",
    "administrator", "admin12345", "changeme123", "willkommen", "willkommen1", "hallo12345",
}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> tuple[bool, bool]:
    """Return ``(valid, needs_rehash)``. Runs a dummy verification for unknown users
    so that response times do not reveal whether an account exists."""
    if not password_hash:
        try:
            _hasher.verify(_DUMMY_HASH, password)
        except VerificationError:
            pass
        return False, False
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, False
    return True, _hasher.check_needs_rehash(password_hash)


def password_problems(password: str, *, username: str | None = None, email: str | None = None) -> list[str]:
    """Validate a new password; returns a list of German error messages."""
    settings = get_settings()
    problems: list[str] = []
    if len(password) < settings.password_min_length:
        problems.append(f"Das Passwort muss mindestens {settings.password_min_length} Zeichen lang sein.")
    if len(password) > 256:
        problems.append("Das Passwort darf höchstens 256 Zeichen lang sein.")
    lowered = password.casefold()
    if lowered in _COMMON_PASSWORDS:
        problems.append("Dieses Passwort ist zu häufig und daher unsicher.")
    if username and lowered == username.casefold():
        problems.append("Das Passwort darf nicht dem Benutzernamen entsprechen.")
    if email and lowered == email.casefold():
        problems.append("Das Passwort darf nicht der E-Mail-Adresse entsprechen.")
    if len(set(password)) < 4 and len(password) >= 1:
        problems.append("Das Passwort ist zu einfach.")
    return problems
