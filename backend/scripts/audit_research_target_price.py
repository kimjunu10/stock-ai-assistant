"""증권사 리포트 목표주가 데이터 감사 (읽기 전용). prompt.md §1~2.

공유 Supabase 를 절대 변경하지 않는다. select 만 수행한다.
target_price 가 None 이라는 이유만으로 '목표주가 없음'으로 판단하지 않고,
페이지 텍스트·표 데이터에 실제 목표주가가 있는지까지 확인해 상태를 분류한다.

상태 분류(추정, 감사용):
  - stated_candidate : 페이지/표에 '목표주가 NNN,NNN' 현재값 후보가 명확히 존재
  - history_only     : 목표주가 표기는 있으나 '변동추이/제시일자' 이력표 형태(현재값 확정 애매)
  - not_stated       : 목표주가 표기 자체가 페이지 텍스트에 없음
  - needs_review     : 위로 분류 불가(표 구조 손실 등)

실행(VM staging/운영 컨테이너 내부, 읽기전용):
  docker cp scripts/audit_research_target_price.py <container>:/tmp/a.py
  docker exec <container> python /tmp/a.py            # 전체 종목
  docker exec <container> python /tmp/a.py 005930 8   # 특정 종목 + 표본 N개 상세
"""

from __future__ import annotations

import re
import sys

from app.db.client import get_supabase_client

# 현재 목표주가 후보: '목표주가/목표가/TP' 근처의 6자리 이하 원화 금액.
TP_LABEL_RE = re.compile(r"(목표\s*주가|목표가|목표\s*가격|target\s*price|TP)\b", re.I)
WON_RE = re.compile(r"\b\d{2,3},\d{3}\b")  # 74,000 / 320,000 등
# 이력표 신호: '변동추이', '제시일자', 여러 날짜가 세로로 나열
HISTORY_RE = re.compile(r"(변동\s*추이|제시\s*일자|괴리율)")


def classify(text: str) -> str:
    if not text:
        return "not_stated"
    has_label = bool(TP_LABEL_RE.search(text))
    has_won = bool(WON_RE.search(text))
    has_history = bool(HISTORY_RE.search(text))
    if has_label and has_history:
        return "history_only"
    if has_label and has_won:
        return "stated_candidate"
    if has_label and not has_won:
        return "needs_review"
    return "not_stated"


def main() -> int:
    stock = sys.argv[1] if len(sys.argv) > 1 else None
    n_detail = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    client = get_supabase_client()

    q = client.table("research_reports").select(
        "id,stock_code,broker,title,report_date,investment_opinion,"
        "target_price,target_price_currency,parse_status"
    )
    if stock:
        q = q.eq("stock_code", stock)
    reports = q.order("report_date", desc=True).execute().data or []

    print("=" * 72)
    print(f"[1] research_reports 전수 (stock={stock or 'ALL'}) — {len(reports)}건")
    print("=" * 72)
    parse_dist: dict[str, int] = {}
    tp_null = 0
    for r in reports:
        parse_dist[r.get("parse_status")] = parse_dist.get(r.get("parse_status"), 0) + 1
        if r.get("target_price") in (None, ""):
            tp_null += 1
    print(f"  parse_status 분포: {parse_dist}")
    print(f"  target_price NULL: {tp_null}/{len(reports)}")

    # ── 페이지 텍스트로 실제 목표주가 존재 여부 감사 ──
    print()
    print("=" * 72)
    print("[2] 페이지 텍스트 기반 목표주가 상태 분류 (target_price NULL의 진짜 원인)")
    print("=" * 72)
    status_counts: dict[str, int] = {}
    by_broker: dict[str, dict[str, int]] = {}
    samples: dict[str, list] = {}
    for r in reports:
        pages = (
            client.table("research_report_pages")
            .select("page_number,plain_text")
            .eq("report_id", r["id"])
            .order("page_number")
            .execute()
            .data
            or []
        )
        # 리포트 단위: 페이지 중 하나라도 stated_candidate 면 stated 우선, 아니면 history/none
        report_status = "not_stated"
        evidence = None
        for p in pages:
            st = classify(p.get("plain_text") or "")
            if st == "stated_candidate":
                report_status = "stated_candidate"
                m = WON_RE.search(p.get("plain_text") or "")
                evidence = (p["page_number"], m.group(0) if m else None)
                break
            if st == "history_only" and report_status == "not_stated":
                report_status = "history_only"
                evidence = (p["page_number"], "history_table")
            elif st == "needs_review" and report_status == "not_stated":
                report_status = "needs_review"
        status_counts[report_status] = status_counts.get(report_status, 0) + 1
        b = r.get("broker") or "?"
        by_broker.setdefault(b, {}).setdefault(report_status, 0)
        by_broker[b][report_status] += 1
        samples.setdefault(report_status, [])
        if len(samples[report_status]) < 3:
            samples[report_status].append(
                (r.get("broker"), r.get("report_date"), str(r.get("title"))[:32], evidence)
            )

    print(f"  상태 분포: {status_counts}")
    print("  증권사별:")
    for b, d in sorted(by_broker.items()):
        print(f"    {b}: {d}")
    print("  상태별 표본:")
    for st, rows in samples.items():
        print(f"    [{st}]")
        for row in rows:
            print(f"      {row}")

    # ── 표본 상세 덤프 ──
    if stock and n_detail:
        print()
        print("=" * 72)
        print(f"[3] 표본 상세 (최근 {n_detail}건) — 목표주가 페이지·표 원문")
        print("=" * 72)
        for r in reports[:n_detail]:
            print(f"\n── {r.get('report_date')} | {r.get('broker')} | "
                  f"opinion={r.get('investment_opinion')} | tp={r.get('target_price')}")
            pages = (
                client.table("research_report_pages")
                .select("page_number,plain_text")
                .eq("report_id", r["id"])
                .order("page_number")
                .execute()
                .data
                or []
            )
            for p in pages:
                txt = p.get("plain_text") or ""
                mlab = TP_LABEL_RE.search(txt)
                if mlab:
                    idx = mlab.start()
                    snip = txt[max(0, idx - 20) : idx + 120].replace("\n", " ")
                    print(f"   p{p['page_number']}: ...{snip}...")
                    break
            tables = (
                client.table("research_report_tables")
                .select("page_number,title,headers,value_kind")
                .eq("report_id", r["id"])
                .execute()
                .data
                or []
            )
            tp_tables = [
                t
                for t in tables
                if TP_LABEL_RE.search(str(t.get("title") or "") + str(t.get("headers") or ""))
            ]
            for t in tp_tables[:2]:
                print(
                    f"   [표] p{t['page_number']} vk={t.get('value_kind')} "
                    f"title={t.get('title')} headers={t.get('headers')}"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
