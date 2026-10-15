"""Generate the company document estate, seed the portal database and index everything.

Usage:  python scripts/build_portal.py [--reset]
  --reset  delete the portal database (users, sessions, logs, uploads metadata) and start fresh
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from portal import company_data, db, indexer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    if args.reset and db.DB_PATH.exists():
        db.DB_PATH.unlink()
    print(company_data.build())
    db.init()
    with db.conn() as c:   # refresh generated documents' metadata, keep uploads
        for d in __import__("json").loads(company_data.MANIFEST.read_text()):
            db.upsert_document(c, d)
    print(indexer.build_all())


if __name__ == "__main__":
    main()
