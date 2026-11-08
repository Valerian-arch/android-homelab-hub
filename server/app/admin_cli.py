"""Emergency admin tools, run on the server itself.

Lost the admin password AND all recovery codes?

    docker exec -it homelab-hub python -m app.admin_cli reset-password

(or ``python -m app.admin_cli reset-password`` in the server folder when not using Docker).
Prints a new temporary password that must be changed at the next login and logs out
every browser session. Paired phones are not affected.
"""

from __future__ import annotations

import sys

from .auth import AuthStore
from .bootstrap import _banner, reset_admin_password
from .config import load_settings
from .db import Database

USAGE = "usage: python -m app.admin_cli reset-password"


def main(argv: list[str]) -> int:
    if argv != ["reset-password"]:
        print(USAGE, file=sys.stderr)
        return 2
    settings = load_settings()
    db = Database(settings.data_dir / "hub.db")
    db.init()
    password = reset_admin_password(AuthStore(db, settings.session_hours))
    print(_banner("admin password reset", password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
