"""RAG Phase 1 마이그레이션(0012~0015)을 순서대로 psql 로 적용한다.

- DATABASE_URL(settings) 사용. 비밀값은 출력하지 않는다.
- --check: 적용 없이 대상 파일만 나열.
- --rollback: rollback/ 폴더의 down 스크립트를 역순으로 실행.
- ON_ERROR_STOP=1 로 첫 오류에서 중단한다.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402

MIGRATIONS = [
    "0012_rag_core.sql",
    "0013_research_reports.sql",
    "0014_rag_hybrid_search.sql",
    "0015_rag_rls_storage.sql",
    "0016_rag_search_semantic.sql",
]
ROLLBACKS = [
    "0016_rag_search_semantic_down.sql",
    "0015_rag_rls_storage_down.sql",
    "0014_rag_hybrid_search_down.sql",
    "0013_research_reports_down.sql",
    "0012_rag_core_down.sql",
]

MIG_DIR = Path(__file__).resolve().parents[1] / "migrations"


def run_sql(path: Path) -> None:
    print(f"→ applying {path.name}")
    subprocess.run(
        ["psql", settings.database_url, "-v", "ON_ERROR_STOP=1", "-f", str(path)],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rollback", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    files = ROLLBACKS if args.rollback else MIGRATIONS
    base = MIG_DIR / "rollback" if args.rollback else MIG_DIR

    if args.check:
        for f in files:
            p = base / f
            print(f"{'OK ' if p.exists() else 'MISSING'} {p}")
        return 0

    if not settings.database_url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 1

    for f in files:
        run_sql(base / f)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
