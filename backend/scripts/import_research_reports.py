"""Inventory or import local analyst PDFs without creating embeddings.

Default mode is read-only. Pass --apply only after applying
``scripts/research_reports_schema.sql`` and confirming that redistribution
rights allow private storage.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.db.client import get_supabase_client

STOCK_CODES = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "두산에너빌리티": "034020",
    "한화오션": "042660",
    "현대차": "005380",
}
BUCKET = "research-reports"


@dataclass(frozen=True)
class ParsedReport:
    path: Path
    stock_code: str
    broker: str
    title: str
    published_on: date
    sha256: str
    pages: list[str]

    @property
    def extraction_status(self) -> str:
        return "text_extracted" if sum(map(len, self.pages)) >= 500 else "needs_ocr"

    @property
    def storage_path(self) -> str:
        return f"{self.stock_code}/{self.published_on.isoformat()}/{self.sha256[:16]}.pdf"


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def parse_report(path: Path) -> ParsedReport:
    parts = _nfc(path.stem).split("_", 3)
    if len(parts) != 4:
        raise ValueError(f"Expected date_company_broker_title filename: {path.name}")
    published, company, broker, title = parts
    stock_code = STOCK_CODES.get(company)
    if not stock_code:
        raise ValueError(f"Unsupported company in filename: {company}")

    completed = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=True,
        capture_output=True,
    )
    text = completed.stdout.decode("utf-8", errors="replace")
    pages = [page.strip() for page in text.split("\f")]
    if pages and not pages[-1]:
        pages.pop()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ParsedReport(
        path=path,
        stock_code=stock_code,
        broker=broker,
        title=title,
        published_on=date.fromisoformat(published),
        sha256=digest,
        pages=pages,
    )


def import_report(report: ParsedReport) -> str:
    client = get_supabase_client()
    existing = (
        client.table("research_reports")
        .select("id")
        .eq("sha256", report.sha256)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        return "skipped"

    client.storage.from_(BUCKET).upload(
        report.storage_path,
        report.path,
        {"content-type": "application/pdf", "upsert": "false"},
    )
    inserted = (
        client.table("research_reports")
        .insert(
            {
                "stock_code": report.stock_code,
                "broker": report.broker,
                "title": report.title,
                "published_on": report.published_on.isoformat(),
                "storage_path": report.storage_path,
                "source_filename": _nfc(report.path.name),
                "sha256": report.sha256,
                "page_count": len(report.pages),
                "file_size_bytes": report.path.stat().st_size,
                "extraction_status": report.extraction_status,
            }
        )
        .execute()
        .data
    )
    report_id = inserted[0]["id"]
    page_rows = [
        {
            "report_id": report_id,
            "page_number": number,
            "text_content": page,
            "char_count": len(page),
        }
        for number, page in enumerate(report.pages, start=1)
    ]
    if page_rows:
        client.table("research_report_pages").insert(page_rows).execute()
    return "imported"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Upload and insert; default is dry-run"
    )
    args = parser.parse_args()

    reports = [parse_report(path) for path in sorted(args.root.rglob("*.pdf"))]
    needs_ocr = sum(report.extraction_status == "needs_ocr" for report in reports)
    total_bytes = sum(report.path.stat().st_size for report in reports)
    text_chars = sum(len(page) for report in reports for page in report.pages)
    print(
        f"reports={len(reports)} pdf_bytes={total_bytes} text_chars={text_chars} "
        f"needs_ocr={needs_ocr} mode={'apply' if args.apply else 'dry-run'}"
    )
    if args.apply:
        outcomes = [import_report(report) for report in reports]
        print(f"imported={outcomes.count('imported')} skipped={outcomes.count('skipped')}")


if __name__ == "__main__":
    main()
