from __future__ import annotations

import getpass

from app.services.admin_auth_service import hash_password


def main() -> None:
    first = getpass.getpass("Admin password: ")
    second = getpass.getpass("Repeat password: ")
    if not first or first != second:
        raise SystemExit("passwords are empty or do not match")
    print(hash_password(first))


if __name__ == "__main__":
    main()
