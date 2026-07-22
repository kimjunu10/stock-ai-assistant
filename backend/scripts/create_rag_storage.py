"""비공개 리포트 Storage 버킷(research-reports-private)을 멱등 생성한다 (SPEC §7).

- 기본은 dry-run(현황만 출력). 실제 생성은 --apply.
- public=false 로 생성하고, 이미 있으면 건드리지 않는다.
- 비밀값은 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.client import get_supabase_client  # noqa: E402

BUCKET = "research-reports-private"


def _bucket_name(b) -> str | None:
    if isinstance(b, dict):
        return b.get("name")
    return getattr(b, "name", None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제 생성. 없으면 dry-run.")
    args = ap.parse_args()

    sb = get_supabase_client()
    existing = {_bucket_name(b) for b in sb.storage.list_buckets()}
    print(f"기존 버킷 수: {len(existing)}")

    if BUCKET in existing:
        print(f"OK 이미 존재: {BUCKET}")
        return 0

    if not args.apply:
        print(f"[dry-run] 생성 예정(비공개): {BUCKET}  — 실제 생성하려면 --apply")
        return 0

    sb.storage.create_bucket(BUCKET, options={"public": False})
    print(f"생성됨(비공개): {BUCKET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
