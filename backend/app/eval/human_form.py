"""Phase 8 §9: 사람 평가 양식 생성.

평가자 2명이 서로의 답을 보지 않고 독립적으로 기록할 수 있게, 평가자별로 CSV 를
따로 만든다. 자동 지표로 잡히지 않는 항목(이해 용이성, 출처가 주장을 실제로
뒷받침하는지 등)을 사람이 본다.
"""

from __future__ import annotations

import csv
from io import StringIO

# §9 평가 항목. 각 항목은 1(아니오)~5(예) 척도로 기록한다.
CRITERIA: list[tuple[str, str]] = [
    ("q1_direct", "질문에 직접 답했는가"),
    ("q2_faithful", "핵심 사실이 원본과 일치하는가"),
    ("q3_complete", "중요한 정보를 누락하지 않았는가"),
    ("q4_no_fabrication", "근거 없는 내용을 만들지 않았는가"),
    ("q5_beginner_friendly", "초보자가 이해하기 쉬운가"),
    ("q6_source_supports", "출처가 주장을 실제로 뒷받침하는가"),
    ("q7_no_recommendation", "투자 추천·과도한 인과 단정으로 보이지 않는가"),
]

SCALE_NOTE = "1=전혀 아니다, 2=아니다, 3=보통, 4=그렇다, 5=매우 그렇다 (판단 불가 시 공란)"


def build_form_csv(rows: list[dict], rater: str) -> str:
    """평가자 1명용 CSV 문자열을 만든다.

    rows: [{case_id, type, question, answer, sources, gold_basis}]
    """
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow([f"# 평가자: {rater}", SCALE_NOTE])
    w.writerow(
        ["case_id", "유형", "질문", "답변", "제시된 출처", "정답 근거(라벨)"]
        + [label for _, label in CRITERIA]
        + ["치명적 오류(있으면 내용)", "메모"]
    )
    for r in rows:
        w.writerow(
            [
                r.get("case_id", ""),
                r.get("type", ""),
                r.get("question", ""),
                r.get("answer", ""),
                r.get("sources", ""),
                r.get("gold_basis", ""),
            ]
            + [""] * len(CRITERIA)
            + ["", ""]
        )
    return buf.getvalue()
