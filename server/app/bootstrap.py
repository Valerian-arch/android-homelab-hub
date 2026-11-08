"""First-run admin creation and the emergency password reset."""

from __future__ import annotations

import sys

from .auth import AuthStore, generate_password
from .config import Settings
from .crypto import hash_password


def _banner(title: str, password: str) -> str:
    line = "=" * 64
    return (
        f"\n{line}\n"
        f"  Homelab Hub: {title}\n\n"
        f"  Admin password:  {password}\n\n"
        f"  Log in and change it right away. It is shown only once.\n"
        f"{line}\n"
    )


def ensure_admin(auth: AuthStore, settings: Settings) -> None:
    """Create the admin account on first start, with a password that must be changed."""
    if auth.admin_exists():
        return
    password = settings.initial_admin_password or generate_password()
    auth.create_admin(hash_password(password), must_change=True)
    if not settings.initial_admin_password:
        print(_banner("first start", password), file=sys.stderr, flush=True)


def reset_admin_password(auth: AuthStore) -> str:
    """Set a new random password (must be changed at next login) and log out every session."""
    password = generate_password()
    hashed = hash_password(password)
    if not auth.create_admin(hashed, must_change=True):
        auth.set_password(hashed, must_change=True)
    auth.delete_other_sessions(None)
    return password
