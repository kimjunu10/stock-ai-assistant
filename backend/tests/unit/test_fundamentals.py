from app.api.routes.disclosures import get_disclosures
from app.api.routes.financials import _build_items, _format_won, _latest_report


class FakeQuery:
    def __init__(self, rows):
        self.data = rows

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, value):
        self.data = self.data[:value]
        return self

    def execute(self):
        return self


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return FakeQuery(self.rows)


def test_financial_summary_prefers_latest_quarter_and_cfs():
    rows = [
        {
            "bsns_year": "2025",
            "reprt_code": "11013",
            "fs_div": "CFS",
            "account_nm": "매출액",
            "thstrm_amount": 100_000_000,
            "frmtrm_amount": 50_000_000,
            "amount_type": "quarter",
        },
        {
            "bsns_year": "2025",
            "reprt_code": "11014",
            "fs_div": "OFS",
            "account_nm": "매출액",
            "thstrm_amount": 90_000_000,
            "frmtrm_amount": 100_000_000,
            "amount_type": "quarter",
        },
        {
            "bsns_year": "2025",
            "reprt_code": "11014",
            "fs_div": "CFS",
            "account_nm": "매출액",
            "thstrm_amount": 120_000_000,
            "frmtrm_amount": 100_000_000,
            "amount_type": "quarter",
        },
    ]

    assert _latest_report(rows) == ("2025", "11014")
    item = _build_items(rows, "2025", "11014")[0]
    assert item.display == "1억원"
    assert item.yoyPct == 20.0
    assert item.note == "2025년 3분기"


def test_format_won_handles_trillion_and_negative_amounts():
    assert _format_won(79_140_500_000_000) == "79조 1,405억원"
    assert _format_won(-350_000_000_000) == "-3,500억원"


def test_disclosures_are_mapped_to_public_response():
    client = FakeClient(
        [
            {
                "id": 7,
                "title": "분기보고서",
                "disclosed_at": "2026-07-16T00:00:00+00:00",
                "disclosure_type": "정기공시",
                "viewer_url": "https://dart.fss.or.kr/report",
            }
        ]
    )

    response = get_disclosures("005930", client, 3)

    assert response.items[0].date == "2026.07.16"
    assert response.items[0].viewerUrl == "https://dart.fss.or.kr/report"
