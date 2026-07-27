# Phase 8 · Stable canonical news Gold

## 결과

뉴스 Gold의 canonical 식별자를 재색인 때마다 바뀌는 chunk UUID에서
`news_clusters.id`로 전환했다. 홀드아웃 Agent와 개발셋은 실행하지 않았으며,
preflight만 실행해 40문항 실행 준비 상태를 확인했다.

- Gold 검토 기준 시각: `2026-07-27T12:38:03+09:00`
- preflight 실행 시각: `2026-07-27T13:14:37.852460+09:00`
- preflight: **PASS**
- 뉴스 canonical Gold 해석: **6/6**
- 홀드아웃 Agent 실행: **0/40**
- event-equivalent 추가 승인: **없음**

## 근본 원인

기존 `gold_sources.source_id`는 RAG chunk UUID였다. 같은
`news_clusters.id`의 내용이 갱신되어 재색인되면 새 document/chunk UUID가
생기므로, 사건은 동일해도 과거 chunk가 비현행이 되어 preflight가 실패했다.
`h-news-23`은 canonical 사건 `7108`이 유지되는 동안 chunk UUID만
`518f…`·`575e…` → `8fa2…` → `5683…`으로 바뀐 대표 사례다.

## 변경된 Gold 계약

```json
{
  "source_type": "news_event",
  "source_id": null,
  "canonical_id": "news_clusters.id=7108"
}
```

- canonical 정답은 `news_clusters.id` 하나다.
- preflight는 canonical cluster가 존재하는지 확인한다.
- 그 cluster의 `is_current=true` RAG document와 `is_active=true` chunk를
  DB에서 읽기 전용으로 해석한다.
- resolved chunk의 `source_locator.cluster_id`가 canonical cluster와 다르거나,
  cluster·현행 document·활성 chunk가 없으면 abort한다.
- 다른 cluster는 자동 정답으로 인정하지 않는다.
- event-equivalent는 기존 사람 승인 파일에 등록된 별도 cluster만 인정한다.
- strict Recall@K·Hit@1·MRR은 검색 결과에 기록된 cluster 순서와 canonical
  cluster를 비교한다. chunk UUID는 strict 적중 판정에 쓰지 않는다.

## 홀드아웃 뉴스 Gold와 preflight 해석

| 문항 | canonical cluster | resolved document | resolved chunk |
|---|---:|---|---|
| h-news-20 | 7131 | `9b1b651f-1299-486d-8dc1-7e07565674a5` | `dd8e7f2e-fcc5-478c-bb30-bfb24cfbefac` |
| h-news-21 | 7181 | `11fadd1d-d30e-41d8-ab36-4c1d59610dc5` | `44784745-5e5a-4d3a-b163-dd3f8b5b6bd6` |
| h-news-22 | 6889 | `8457ebec-3b9e-45b1-b791-dbd918d2d72b` | `789d528d-85ef-4d0b-9ced-6c6670f71791` |
| h-news-23 | 7108 | `85545c69-9b42-4cd7-8ddd-3979b1df294d` | `5683c8fe-60bd-475c-9ce5-bb725b8c5fd2` |
| h-news-24 | 7014 | `acae810d-c7f8-426a-9dda-a3c9d867e161` | `f226617d-352c-417b-8a91-1d32dca5bf21` |
| h-news-25 | 7149 | `d8c8775e-f383-43c6-b022-84691f4e5884` | `e98f0d54-0c73-4f2a-a744-3460478eb4e2` |

위 document/chunk ID는 preflight 시점의 감사값이며 정답으로 고정되지 않는다.
다음 실행 전 preflight가 같은 canonical cluster에서 다시 해석한다. 기존 chunk와
변경 근거는 `eval/stable_news_gold_audit.json`에 보존했다.

## 상대 기간 검사

질문 또는 `expected_args.search_news.relative_period`에 상대 기간이 명시된
문항만 실행 시각 기준으로 검사한다. “최근 7일”, “최근 한 달”, “이번 주”,
“오늘”, “어제”, 일반 “최근”을 각각 Tool 계약의 상대 기간으로 변환한다.
상대 기간이 없는 특정 사건 질문은 Gold가 오래됐다는 이유만으로 abort하지 않는다.

이번 홀드아웃에는 명시적 상대 기간 문항이 없어 40건 모두 상대 기간 검사 대상에서
제외됐고, 비현행 Gold 검사는 별도로 6/6 통과했다.

## 테스트

- 동일 cluster에서 document/chunk UUID가 바뀌어도 통과
- 다른 cluster locator면 abort
- canonical cluster 없음 또는 현행 활성 chunk 없음이면 abort
- canonical cluster 반환 시 strict hit
- 실제 검색 순서 기준 Hit@1·MRR
- 상대 기간 있음/없음
- 기존 평가 기반·지표 회귀

## 변경 범위

제품 Agent·Tool·Retriever·시스템 프롬프트와 뉴스 DB는 변경하지 않았다.
질문과 canonical 사건도 변경하지 않았다. 변경은 평가 스키마, 뉴스 Gold
resolver, 평가 데이터의 표현, preflight·검증 스크립트, 단위 테스트와 감사
산출물에 한정된다.

홀드아웃 40문항은 실행하지 않았으며, 현재 상태는 **실행 준비됨**이다.
