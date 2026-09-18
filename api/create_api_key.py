"""Issue an API key for a user. Prints the key once; only its SHA-256 hash is stored.

    python -m api.create_api_key --user-id alice --role customer [--tenant-id acme]
"""
import argparse
import secrets

import yaml

from api.auth import hash_key
from config.settings import API_SETTINGS
from knowledge_bases.kb3_rbac import known_roles


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", required=True)
    ap.add_argument("--role", required=True, choices=known_roles())
    ap.add_argument("--tenant-id", default="default")
    args = ap.parse_args()

    path = API_SETTINGS.api_keys_file
    store = (yaml.safe_load(path.read_text()) if path.exists() else None) or {}
    store.setdefault("users", [])
    key = "rag_" + secrets.token_urlsafe(32)
    store["users"].append({"user_id": args.user_id, "role": args.role, "tenant_id": args.tenant_id,
                           "key_sha256": hash_key(key)})
    path.write_text(yaml.safe_dump(store, sort_keys=False))
    print(f"API key for {args.user_id} ({args.role}, tenant {args.tenant_id}) — store it now, it won't be shown again:")
    print(key)


if __name__ == "__main__":
    main()
