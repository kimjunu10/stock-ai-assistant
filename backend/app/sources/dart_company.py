"""OpenDART company.json 응답을 company_profiles 행으로 변환."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_company_profile(stock_code: str, payload: dict[str, Any]) -> dict[str, Any]:
    est_dt = _date(payload.get("est_dt"))
    return {
        "stock_code": stock_code,
        "corp_name": _text(payload.get("corp_name")),
        "corp_name_eng": _text(payload.get("corp_name_eng")),
        "stock_name": _text(payload.get("stock_name")),
        "ceo_nm": _text(payload.get("ceo_nm")),
        "corp_cls": _text(payload.get("corp_cls")),
        "jurir_no": _text(payload.get("jurir_no")),
        "bizr_no": _text(payload.get("bizr_no")),
        "adres": _text(payload.get("adres")),
        "hm_url": _text(payload.get("hm_url")),
        "ir_url": _text(payload.get("ir_url")),
        "phn_no": _text(payload.get("phn_no")),
        "fax_no": _text(payload.get("fax_no")),
        "induty_code": _text(payload.get("induty_code")),
        "est_dt": est_dt,
        "acc_mt": _text(payload.get("acc_mt")),
        "raw_data": payload,
    }


def _text(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _date(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date().isoformat()
    except ValueError:
        return None
