# Phase 10 발표용 핵심 요약

- 성격: **제품 수정 후 동일 홀드아웃 최종 회귀** — 최초 블라인드·일반화 성능 아님
- automatic formal-condition pass: **39/40 (97.50%)**
- news canonical-cluster Recall@K: **2/6 (33.33%)**
- actual Tool execution success: **37/39 문항 (94.87%)**
- final answer completion: **40/40 (100%)**
- 뉴스 기간 정책: 기간 없는 질문 6/6 `relative_period=None`; h-news-22 rank 1 회복
- 뉴스 최종: h-news-20·23·24·25 miss, strict/event-equivalent 모두 33.33%
- 리포트: Recall@K 100%, Hit@1 60%, MRR 0.7667
- 구조화 조회 93.33%, 숫자 83.33%, 단위·기간 100%
- Tool status: ok 47 / no_data 0 / error 0 / null 3, step_limit 0
- P50/P95: 4,496/8,086ms
- 비용: 총 $0.272251, 문항당 $0.006806
- 주의: formal 97.5%는 RAG 정확도가 아니다. h-na-09에서 실제 허위 비교 답변을
  Solar Judge가 통과시킨 false positive가 확인됐다.
- 종료 판정: **치명적인 production 장애가 남아 종료 불가**
