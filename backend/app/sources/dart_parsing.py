"""OpenDART 응답 파싱/구조화 유틸.

- corpCode ZIP → {stock_code: corp_code} 매핑
- document ZIP → 원문 텍스트 (마크업 제거)
- structured_disclosures 저장을 위한 record_key / summary_text / normalized_data 생성
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree as ET

# corpCode/문서 파싱 --------------------------------------------------------


def parse_corp_code_map(zip_members: dict[str, bytes]) -> dict[str, str]:
    """CORPCODE.xml → {6자리 stock_code: 8자리 corp_code}. 상장사만 포함."""

    xml_bytes = None
    for name, data in zip_members.items():
        if name.upper().endswith("CORPCODE.XML") or name.upper().endswith(".XML"):
            xml_bytes = data
            break
    if xml_bytes is None:
        raise RuntimeError("corpCode ZIP 안에서 XML을 찾지 못함")

    root = ET.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for item in root.iter("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        if stock_code and corp_code and re.fullmatch(r"\d{6}", stock_code):
            mapping[stock_code] = corp_code
    return mapping


def extract_document_text(zip_members: dict[str, bytes], rcept_no: str) -> str:
    """document ZIP → 원문 텍스트. 메인 문서({rcept_no}.xml) 우선, 없으면 전체 병합."""

    def decode(data: bytes) -> str:
        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    main_name = f"{rcept_no}.xml"
    ordered: list[str] = []
    if main_name in zip_members:
        ordered.append(main_name)
    ordered.extend(n for n in zip_members if n != main_name and n.lower().endswith(".xml"))

    texts = [_markup_to_text(decode(zip_members[name])) for name in ordered]
    return "\n\n".join(t for t in texts if t).strip()


def _markup_to_text(markup: str) -> str:
    """DART 원문 XML/HTML 마크업에서 사람이 읽는 텍스트만 추출."""

    # 주석/처리명령 제거
    text = re.sub(r"<\?.*?\?>", " ", markup, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    # 블록 경계를 개행으로
    text = re.sub(r"</(P|TR|TABLE|TITLE|SECTION-\d|ARTICLE)>", "\n", text, flags=re.IGNORECASE)
    # 나머지 태그 제거
    text = re.sub(r"<[^>]+>", " ", text)
    # 엔티티 정리
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )
    # 공백 정리
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]*\n+", "\n\n", text)
    return text.strip()


# 날짜/숫자 정규화 ----------------------------------------------------------

_DATE_RE = re.compile(r"(\d{4})[.\-/년\s]*(\d{1,2})[.\-/월\s]*(\d{1,2})")


def parse_dart_date(value: str | None) -> datetime | None:
    """YYYYMMDD / YYYY-MM-DD / 'YYYY년 MM월 DD일' → UTC datetime(자정)."""

    if not value:
        return None
    s = str(value).strip()
    if re.fullmatch(r"\d{8}", s):
        try:
            return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), tzinfo=UTC)
        except ValueError:
            return None
    m = _DATE_RE.search(s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=UTC)
        except ValueError:
            return None
    return None


def parse_amount(value: Any) -> int | None:
    """'1,234' / '-' / '' → int | None. 순수 정수 금액만 반환."""

    if value is None:
        return None
    s = str(value).strip().replace(",", "")
    if s in ("", "-", "―", "－", "N/A"):
        return None
    m = re.fullmatch(r"-?\d+", s)
    if m:
        try:
            return int(s)
        except ValueError:
            return None
    return None


# record_key / summary / normalized (SPEC §4-3, §4-4) ----------------------

# 업무 내용과 무관한 API 메타 필드 — record_key 해시 입력에서 제외.
META_FIELDS = frozenset({"status", "message", "corp_code", "corp_cls", "corp_name", "stock_code"})


def _clean_for_hash(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in META_FIELDS}


# 업무 내용 유무 판정에서 제외할 필드. 메타 필드 + 접수번호(rcept_no) +
# 이력이 없어도 항상 채워지는 결산기준일(stlm_dt). 이들만 값이 있고 나머지 업무
# 필드가 전부 비어 있으면 "빈 행"으로 본다.
# (rcept_no는 record_key 계산용 META_FIELDS에는 넣지 않는다 — 기존 키 불변 유지.)
_NON_BUSINESS_FIELDS = META_FIELDS | {"rcept_no", "stlm_dt"}

# "비어 있음"으로 취급할 값 (null / 공백 / 대시류).
_EMPTY_VALUES = {"", "-", "―", "－", "N/A", "해당사항없음", "해당없음"}


def has_business_content(row: dict[str, Any]) -> bool:
    """메타·결산일을 제외한 업무 필드에 실제 값이 하나라도 있으면 True.

    OpenDART 정기보고서 API는 이력이 없는 보고기간에도 status=013 대신
    모든 업무 필드가 '-'인 행 1개를 반환하는 경우가 있다. 그런 빈 행을 걸러낸다.
    """

    for key, value in row.items():
        if key in _NON_BUSINESS_FIELDS:
            continue
        v = "" if value is None else str(value).strip()
        if v not in _EMPTY_VALUES:
            return True
    return False


def make_record_key(
    source_api: str,
    rcept_no: str | None,
    row: dict[str, Any],
    distinguishing_fields: list[str] | None = None,
) -> str:
    """원본 행을 결정적으로 식별하는 SHA-256 키 (SPEC §4-3).

    안정적인 구분 필드가 있으면 (source_api, rcept_no, 구분 필드)로,
    없으면 (source_api, rcept_no, 정제된 raw_data 전체)로 canonical JSON 해시.
    행 인덱스/반환 순서는 사용하지 않는다.
    """

    if distinguishing_fields:
        payload: dict[str, Any] = {
            f: row.get(f) for f in distinguishing_fields if row.get(f) not in (None, "")
        }
    else:
        payload = _clean_for_hash(row)

    canonical = json.dumps(
        {"source_api": source_api, "rcept_no": rcept_no or "", "fields": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# 정기보고서 4종의 안정적 구분 필드 (동일 rcept_no 안에서 행을 구분).
REGULAR_DISTINGUISHING: dict[str, list[str]] = {
    "stockTotqySttus": ["se", "stlm_dt"],
    "tesstkAcqsDspsSttus": ["stock_knd", "acqs_mth1", "acqs_mth2", "acqs_mth3", "stlm_dt"],
    "alotMatter": ["se", "stock_knd", "stlm_dt"],
    "irdsSttus": ["isu_dcrs_de", "isu_dcrs_stle", "isu_dcrs_stock_knd", "stlm_dt"],
}


def build_summary_text(name_ko: str, corp_name: str, rcept_no: str | None, row: dict) -> str:
    """LLM 없이 원본 필드를 '한글 필드명: 값' 형태로 결정론적 문장화 (SPEC §4-3).

    한글 라벨 매핑이 없는 필드는 원본 키를 그대로 쓰되, 메타/빈 필드는 제외한다.
    """

    parts = [f"{corp_name} {name_ko}"]
    if rcept_no:
        parts.append(f"접수번호 {rcept_no}")
    detail = []
    for key, value in row.items():
        if key in META_FIELDS:
            continue
        v = "" if value is None else str(value).strip()
        if v in ("", "-"):
            continue
        label = FIELD_LABELS.get(key, key)
        detail.append(f"{label}: {v}")
    if detail:
        parts.append(", ".join(detail))
    return " / ".join(parts)


# 자주 등장하는 필드의 한글 라벨 (없으면 원본 키 사용).
FIELD_LABELS: dict[str, str] = {
    "rcept_no": "접수번호",
    "se": "구분",
    "stock_knd": "주식종류",
    "isu_stock_totqy": "발행할주식총수",
    "now_to_isu_stock_totqy": "현재까지발행한주식총수",
    "istc_totqy": "발행주식총수",
    "tesstk_co": "자기주식수",
    "distb_stock_co": "유통주식수",
    "thstrm": "당기",
    "frmtrm": "전기",
    "lwfr": "전전기",
    "bsis_qy": "기초수량",
    "change_qy_acqs": "취득수량",
    "change_qy_dsps": "처분수량",
    "change_qy_incnr": "소각수량",
    "trmend_qy": "기말수량",
    "isu_dcrs_de": "발행감소일자",
    "isu_dcrs_stle": "발행감소형태",
    "isu_dcrs_qy": "수량",
    "stlm_dt": "결산기준일",
    "nstk_ostk_cnt": "신주보통주식수",
    "nstk_estk_cnt": "신주기타주식수",
    "fdpp_fclt": "자금조달목적",
    "ic_mthn": "증자방식",
    "od_a_at_t": "이사회출석이사수",
    "aqpln_stk_ostk": "취득예정주식수보통주",
    "aqexpd_bgd": "취득예상기간시작",
    "aqexpd_edd": "취득예상기간종료",
}


# 자기주식 취득/처분 결정의 표준 normalized 매핑 (SPEC §4-3 고빈도 유형).
# 원본 필드 → 표준 키. 숫자/날짜/문자열을 원본에서 직접 파싱한다(LLM 미사용).
# 필수 키: 주식 수·금액·기간·목적. 원본에 값이 없으면 억지로 만들지 않는다.
_TREASURY_ACQ_MAP = {
    "numeric": {
        "aqpln_stk_ostk": "acq_planned_shares_common",  # 취득예정 보통주식수
        "aqpln_stk_estk": "acq_planned_shares_other",  # 취득예정 기타주식수
        "aqpln_prc_ostk": "acq_planned_amount_common",  # 취득예정금액(보통주)
        "aqpln_prc_estk": "acq_planned_amount_other",  # 취득예정금액(기타주)
    },
    "date": {
        "aq_dd": "decision_date",  # 취득결정일(이사회)
        "aqexpd_bgd": "acq_period_start",  # 취득예상기간 시작
        "aqexpd_edd": "acq_period_end",  # 취득예상기간 종료
    },
    "text": {
        "aq_pp": "purpose",  # 취득목적
        "aq_mth": "acq_method",  # 취득방법
    },
    # 필수 항목(하나라도 채워지지 않으면 보고에 사유 기록)
    "required": (
        "acq_planned_shares_common",
        "acq_planned_amount_common",
        "acq_period_start",
        "acq_period_end",
        "purpose",
    ),
}

_TREASURY_DP_MAP = {
    "numeric": {
        "dppln_stk_ostk": "disp_planned_shares_common",  # 처분예정 보통주식수
        "dppln_stk_estk": "disp_planned_shares_other",  # 처분예정 기타주식수
        "dppln_prc_ostk": "disp_planned_amount_common",  # 처분예정금액(보통주)
        "dppln_prc_estk": "disp_planned_amount_other",  # 처분예정금액(기타주)
        "dpstk_prc_ostk": "disp_unit_price_common",  # 처분 단가(보통주)
        "dpstk_prc_estk": "disp_unit_price_other",  # 처분 단가(기타주)
    },
    "date": {
        "dp_dd": "decision_date",  # 처분결정일(이사회)
        "dpprpd_bgd": "disp_period_start",  # 처분예정기간 시작
        "dpprpd_edd": "disp_period_end",  # 처분예정기간 종료
    },
    "text": {
        "dp_pp": "purpose",  # 처분목적
        "dp_m_mkt": "disp_method_market",  # 처분방법(장내)
    },
    "required": (
        "disp_planned_shares_common",
        "disp_planned_amount_common",
        "disp_period_start",
        "disp_period_end",
        "purpose",
    ),
}

TREASURY_NORMALIZE = {
    "tsstkAqDecsn": _TREASURY_ACQ_MAP,
    "tsstkDpDecsn": _TREASURY_DP_MAP,
}


def normalize_treasury(source_api: str, row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """자기주식 취득/처분 raw_data → 표준 normalized_data.

    반환: (normalized dict, 원본에 값이 없어 채우지 못한 필수 키 목록).
    숫자는 parse_amount, 날짜는 parse_dart_date로 원본에서 직접 파싱한다.
    """

    spec = TREASURY_NORMALIZE.get(source_api)
    if spec is None:
        return {}, []

    out: dict[str, Any] = {}
    for src, std in spec["numeric"].items():
        amt = parse_amount(row.get(src))
        if amt is not None:
            out[std] = amt
    for src, std in spec["date"].items():
        dt = parse_dart_date(row.get(src))
        if dt is not None:
            out[std] = dt.date().isoformat()
    for src, std in spec["text"].items():
        v = row.get(src)
        v = "" if v is None else str(v).strip()
        if v and v not in _EMPTY_VALUES:
            out[std] = v

    missing = [k for k in spec["required"] if k not in out]
    return out, missing
