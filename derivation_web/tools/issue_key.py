"""Issue, revoke, or list API keys.

Raw keys print exactly once at issuance and are NEVER stored — only the
SHA-256 hash hits the DB. Lose the key, issue a new one and revoke the old.

Usage on VPS (DATABASE_URL must be set; systemd EnvironmentFile already does):
    set -a; . /etc/derivation-web/env; set +a
    PY=/opt/derivation-web/.venv/bin/python
    $PY -m derivation_web.tools.issue_key issue --client-id researka
    $PY -m derivation_web.tools.issue_key list
    $PY -m derivation_web.tools.issue_key revoke --key-id key_xxxxxxxxxxxx
"""

from __future__ import annotations

import argparse
import sys
import uuid

from derivation_web.api.auth import generate_key
from derivation_web.db import repo
from derivation_web.db.session import make_session


def cmd_issue(client_id: str) -> int:
    raw, key_hash = generate_key()
    key_id = f"key_{uuid.uuid4().hex[:12]}"
    with make_session() as session:
        repo.create_api_key(
            session, key_id=key_id, key_hash=key_hash, client_id=client_id
        )
        session.commit()
    print(f"id        : {key_id}")
    print(f"client_id : {client_id}")
    print(f"key       : {raw}")
    print()
    print("SAVE THE KEY NOW. It cannot be recovered — only the SHA-256 hash is stored.")
    return 0


def cmd_revoke(key_id: str) -> int:
    with make_session() as session:
        ok = repo.revoke_api_key(session, key_id)
        if ok:
            session.commit()
            print(f"revoked: {key_id}")
            return 0
    print(f"not found or already revoked: {key_id}", file=sys.stderr)
    return 1


def cmd_list() -> int:
    with make_session() as session:
        rows = repo.list_api_keys(session)
    print(f"{'id':<22} {'client_id':<24} {'created_at':<26} status")
    for row in rows:
        status = (
            "active"
            if row.revoked_at is None
            else f"revoked {row.revoked_at.isoformat()}"
        )
        print(
            f"{row.id:<22} {row.client_id:<24} {row.created_at.isoformat():<26} {status}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="issue_key")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_issue = sub.add_parser("issue", help="issue a new API key")
    p_issue.add_argument("--client-id", required=True)
    p_revoke = sub.add_parser("revoke", help="revoke an existing API key")
    p_revoke.add_argument("--key-id", required=True)
    sub.add_parser("list", help="list all API keys (active + revoked)")
    args = parser.parse_args(argv)

    if args.cmd == "issue":
        return cmd_issue(args.client_id)
    if args.cmd == "revoke":
        return cmd_revoke(args.key_id)
    if args.cmd == "list":
        return cmd_list()
    return 2


if __name__ == "__main__":
    sys.exit(main())
