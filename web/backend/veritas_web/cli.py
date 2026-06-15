"""Veritas Web user management CLI.

Provides commands for managing users when ``VERITAS_AUTH_MODE=basic``.
Uses the same SQLite store as the web backend so that users added here are
immediately available for authentication.

Usage::

    python -m web.backend.veritas_web.cli add-user alice --email alice@lab.org --roles admin,operator
    python -m web.backend.veritas_web.cli list-users
    python -m web.backend.veritas_web.cli delete-user alice
    python -m web.backend.veritas_web.cli change-password alice
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from .auth import BasicAuthProvider
from .config import AuthConfig


def _get_provider(args: argparse.Namespace) -> BasicAuthProvider:
    """Build a ``BasicAuthProvider`` from CLI flags or environment defaults."""
    if getattr(args, "db", None):
        db_path = str(Path(args.db).resolve())
    else:
        config = AuthConfig.from_env()
        db_path = str(config.sqlite_db_path)
    return BasicAuthProvider(db_path)


def cmd_add_user(args: argparse.Namespace) -> int:
    provider = _get_provider(args)
    password = args.password or getpass.getpass(prompt=f"Password for {args.username}: ")
    if not password:
        print("Error: password must not be empty.", file=sys.stderr)
        return 1
    provider.add_user(
        username=args.username,
        password=password,
        email=args.email,
        roles=args.roles or "operator",
    )
    print(f"User {args.username!r} created (roles={args.roles or 'operator'}).")
    return 0


def cmd_list_users(args: argparse.Namespace) -> int:
    provider = _get_provider(args)
    users = provider.list_users()
    if not users:
        print("No users found.")
        return 0
    print(json.dumps(users, indent=2, ensure_ascii=False))
    return 0


def cmd_delete_user(args: argparse.Namespace) -> int:
    provider = _get_provider(args)
    if provider.delete_user(args.username):
        print(f"User {args.username!r} deleted.")
        return 0
    print(f"User {args.username!r} not found.", file=sys.stderr)
    return 1


def cmd_change_password(args: argparse.Namespace) -> int:
    provider = _get_provider(args)
    password = args.password or getpass.getpass(prompt=f"New password for {args.username}: ")
    if not password:
        print("Error: password must not be empty.", file=sys.stderr)
        return 1
    if provider.change_password(args.username, password):
        print(f"Password updated for {args.username!r}.")
        return 0
    print(f"User {args.username!r} not found.", file=sys.stderr)
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="veritas-users",
        description="Manage Veritas Web users (basic auth mode).",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to the SQLite users database. Defaults to VERITAS_USERS_DB or 'web_data/users.db'.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add-user", help="Add or update a user.")
    add.add_argument("username", help="Unique username.")
    add.add_argument("--email", default=None, help="User email address.")
    add.add_argument("--roles", default="operator", help="Comma-separated roles (default: operator).")
    add.add_argument("--password", default=None, help="Password (if omitted, prompted interactively).")

    subparsers.add_parser("list-users", help="List all users.")

    delete = subparsers.add_parser("delete-user", help="Delete a user.")
    delete.add_argument("username", help="Username to delete.")

    change = subparsers.add_parser("change-password", help="Change a user's password.")
    change.add_argument("username", help="Username.")
    change.add_argument("--password", default=None, help="New password (if omitted, prompted interactively).")

    return parser


_COMMANDS = {
    "add-user": cmd_add_user,
    "list-users": cmd_list_users,
    "delete-user": cmd_delete_user,
    "change-password": cmd_change_password,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _COMMANDS[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
