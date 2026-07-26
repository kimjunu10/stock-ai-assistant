from app.api.routes.reports import _download_filename, get_reports


class _Query:
    def __init__(self, rows):
        self.data = rows
        self.count = len(rows)

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args):
        return self

    def in_(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, *_args):
        return self

    def execute(self):
        return self


class _Client:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "research_reports"
        return _Query(self.rows)


def test_report_list_normalizes_korean_and_hides_storage_path():
    result = get_reports(
        "005930",
        _Client(
            [
                {
                    "id": "report-1",
                    "stock_code": "005930",
                    "broker": "하나증권",
                    "title": "메모리 전망",
                    "report_date": "2026-07-08",
                    "investment_opinion": "BUY",
                    "page_count": 4,
                    "storage_bucket": "private",
                    "storage_path": "secret/report.pdf",
                }
            ]
        ),
        limit=8,
        offset=0,
    )

    assert result.items[0].broker == "하나증권"
    assert result.items[0].title == "메모리 전망"
    assert result.items[0].downloadUrl.endswith("/report-1/download")
    assert "storage" not in result.items[0].model_dump()


def test_download_filename_is_safe_and_readable():
    filename = _download_filename(
        {"report_date": "2026-07-08", "broker": "하나/증권", "title": '메모리: "전망"'}
    )
    assert filename == "2026-07-08_하나_증권_메모리_ _전망.pdf"
