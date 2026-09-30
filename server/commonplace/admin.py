"""Administer contributors and inspect the commons from the command line.

    python -m commonplace.admin add-contributor ryan --role curator
    python -m commonplace.admin list-contributors
    python -m commonplace.admin stats
"""

from __future__ import annotations

import argparse
import json
import os

from . import store
from .db import connect


def main() -> None:
    p = argparse.ArgumentParser(prog="commonplace.admin")
    p.add_argument("--db", default=os.environ.get("COMMONPLACE_DB", "commonplace.db"))
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add-contributor", help="Create a contributor and print their token (shown once).")
    a.add_argument("name")
    a.add_argument("--role", default="member", choices=["member", "curator", "admin"])
    sub.add_parser("list-contributors")
    sub.add_parser("stats")
    args = p.parse_args()

    conn = connect(args.db)
    if args.cmd == "add-contributor":
        token = store.add_contributor(conn, args.name, args.role)
        print(f"Created {args.role} '{args.name}'. Token (store it now; it is not shown again):\n{token}")
    elif args.cmd == "list-contributors":
        print(json.dumps(store.list_contributors(conn), indent=2))
    elif args.cmd == "stats":
        print(json.dumps(store.stats(conn), indent=2))


if __name__ == "__main__":
    main()
