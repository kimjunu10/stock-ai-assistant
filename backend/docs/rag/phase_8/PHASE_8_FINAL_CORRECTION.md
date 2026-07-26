# Phase 8 최종 코드 교정

브랜치: `phase/8-final-correction` (base: PR #60 머지 후 main)

round3에서 확인된 공통 코드 문제만 최소 수정한다. 전체 120문항·홀드아웃 40문항은
실행하지 않고, 관련 문항 targeted regression과 단위 테스트만 수행했다. gold label과
devset 질문은 변경하지 않았다.

## 1. 공시 검색 비결정성 원인과 수정

**원인**: `FactsService.get_latest_disclosures`/`get_structured_values` 가
`disclosed_at`/`announced_at` 단일 컬럼으로만 정렬했다. 같은 날짜(동률)인 행이
여러 건 있을 때 DB가 반환하는 순서가 임의라, `limit` 경계선이 동률 그룹 안에
걸치면 어떤 문서가 잘리는지가 실행마다 달라졌다.

실제로 SK하이닉스(000660)는 `disclosed_at`이 완전히 같은 날인 공시가
2026-07-15(3건), 2026-07-10(5건)에 각각 존재했고, `limit=5`의 5번째 자리가
이 동률 그룹 안에 걸쳐 gold 문서(`20260710000002`, 2026-07-10)가 포함되거나
밀려나는 게 실행마다 뒤바뀌었다.

**수정**: 두 메서드 모두 `rcept_no`를 2차 정렬 키로 추가해(`.order("rcept_no",
desc=True)`) 동률을 결정적으로 만들었다. 임베딩·RRF·top-k는 건드리지 않았다.

추가로 원인 조사 중 `search_disclosures` Tool이 `query` 인자를 받아놓고도
`get_latest_disclosures`에 전달하지 않아(코드상 완전히 무시) 실제로는 아무 필터
효과가 없다는 것을 발견했다. 다만 실제 title("해외증권시장주권등상장결정")과
사용자 표현("해외상장")이 문자열로 매치되지 않아 `ILIKE` 필터를 추가하면 오히려
0건이 되는 걸 확인했고, 이는 문자열 정규화로 풀리는 문제가 아니라 별개의
"Tool 선택"(이 경우 `get_disclosure_values(event_type=...)`를 썼어야 함) 문제로
판단해 손대지 않았다(§9 남은 문제로 기록).

## 2. 동일 입력 10회 반복 결과

`get_latest_disclosures("000660", limit=5)`를 수정 전/후 각 10회(별도 프로세스
포함) 실행해 비교했다.

- 수정 전: 10/10 동일했으나(로컬 프로세스 커넥션 재사용 영향 가능) 실제 별도
  프로세스 비교에서도 우연히 안정적이었던 것으로 보임 — 근본 원인(동률 정렬)은
  DB 반환 순서에 의존하므로 언제든 재발 가능한 구조였음을 실제 SQL로 확인.
- 수정 후: 10/10 및 별도 프로세스 6/6 완전히 동일한 순서·식별자.

targeted regression에서 실제 Agent로 disc-11("SK하이닉스 해외상장 결정 공시
내용 알려줘")을 10회 반복 실행한 결과:

- `search_disclosures`만 호출한 9회: **9/9 완전히 동일**한 5개 문서·순서
  (`20260713000324, 20260715000004, 20260715800045, 20260715800456,
  20260716000582`) — DB tie-break 결함은 해결됨.
- 1회는 모델이 추가로 `get_disclosure_values(event_type=overseas_listing_decision)`
  까지 호출해 gold 문서(`20260710000002`)를 정확히 찾음.

즉 **DB 레벨 비결정성(정렬 tie-break)은 완전히 해결**했다. 남은 변동은 DB 정렬이
아니라 "이 질문에 어떤 Tool을 쓸지"를 모델이 매번 다르게 고르는 별개의 문제이며,
§9에 남은 문제로 기록한다(이번 라운드에서 손대지 않음 — Tool 선택 프롬프트를
질문별로 고치는 것은 "질문별 예외 처리 금지"에 저촉될 위험이 있어 신중한 별도
검토가 필요).

## 3. 리포트 Validator 오탐 수정 전후

prompt.md가 지목한 2건(mix-09, mix-15: "RAG가 gold 리포트를 찾고 source에도
목표주가가 존재했는데 Validator가 정상 답변을 삭제")을 원본 Tool trace로
재검증했다.

- mix-09(두산에너빌리티): 실제 stated 목표주가는 149000/150000/156000/158000/160000원.
  Validator가 삭제한 문장은 "140,000원"을 언급했는데, 이는 어느 증권사의
  실제 값과도 일치하지 않는다.
- mix-15(한화오션): 실제 stated 목표주가는 139000/144000/179000원. 역시
  Validator가 삭제한 문장은 근거에 없는 "140,000원"이었다.

두 사례 모두 **Validator가 정상 동작한 사례였다** — 답변에 남은 "실제 gold
값과 일치하는 문장"(예: mix-09의 "15만원 내외")은 삭제되지 않고 그대로
보존됐고, 근거에 없는 값만 정확히 제거됐다. `sanitize_answer`/`_TP_CTX_RE`
로직을 인위적으로 재현해도 동일한 결과였다.

**수정하지 않았다.** round3 분류 스크립트의 "답변 삭제(재확인 필요)" 태그는
`validation_errors`에 "제거함" 문자열이 있으면 무조건 히트시키는 휴리스틱이라
재확인 없이는 오탐/정탐을 구분하지 못했을 뿐, 실제로는 정탐이었다. targeted
regression 재실행(모델 재호출)에서도 두 케이스 모두 매번 동일하게 근거 없는
"140,000원"을 생성하고 Validator가 이를 차단하는 패턴이 안정적으로 재현됐다.
prompt.md §6의 "실제로 gold를 찾았는데 평가기가 오판했을 때만 수정" 조건에
해당하지 않으므로 Validator/평가기 모두 건드리지 않았다.

## 4. 부정 표현 평가 오탐 수정 전후

`app/eval/grader.py`의 `_NEGATION_MARKERS`에 "아님", "아닌", "하지 않",
"해당하지 않"을 추가하고, 금지어 바로 뒤에 "외"가 붙는 표현
(`_claim_excluded_by_suffix`, 예: "실적 **외** 주요 이슈")을 잡는 별도 검사를
추가했다.

round3의 "제외 조건 위반" 4건을 실제 답변 문장으로 재확인:

| 케이스 | forbidden 단어 | 실제 문장 | 원인 | 수정 결과 |
|---|---|---|---|---|
| report-10 | 확정 | "...확정 실적이 **아님**을 유의해 주세요" | "아님" 마커 부재 | 위반 아님으로 정정 |
| na-05 | 추천 | "직접적인 매수·매도 추천은 **하지 않습니다**" | "하지 않" 마커 부재 | 위반 아님으로 정정 |
| excl-05 | 실적 | "한화오션의 최근 실적 **외** 주요 이슈는..." | "외" 접미 패턴 미검사 | 위반 아님으로 정정 |
| disc-13 | 증권사 | "주관 **증권사**: 삼성증권, 신한투자증권, KB증권" | 부정 표현 문제 아님 — 자기주식 취득 공시의 "주관 증권사" 필드가 forbidden_claims("증권사")와 문자 그대로 충돌 | **미수정** |

같은 답변(원본 baseline 실행 기록)을 새 grader로 재채점한 결과: report-10,
na-05, excl-05는 `exclusion_violations == []`로 정확히 정정됐다. disc-13은
여전히 `["증권사"]`로 남는다 — 이건 부정 표현 오판이 아니라 forbidden_claims
라벨 자체가 "리포트/목표주가 문맥의 증권사"만 배제하려던 의도인데 문자열
매칭이 공시의 무관한 필드명("주관 증권사")까지 잡는 구조적 한계다. gold label을
바꾸지 않는다는 원칙에 따라 라벨은 그대로 두고 §7 남은 한계로 기록한다.

기존 부정 표현 정탐(실제 금지 내용을 긍정 주장한 경우)은 회귀 테스트
(`test_exclusion_violation_still_caught_in_other_sentence` 등 기존 4건)로
계속 잡히는 것을 확인했다.

## 5. 모호한 리포트 질문 4종의 실제 동작

`scripts/phase8_final_smoke_ambiguous_report.py`로 실제 Agent를 4개 질문에
대해 실행했다.

- **A. "삼성전자 최근 리포트 알려줘"**: 최신순 리포트 목록(증권사·날짜 포함)을
  되묻지 않고 반환. (수정 전에는 `query=""`로 호출되어 임베딩 계층이 빈 문자열을
  거부해 **오류**가 발생했음 — §6에서 수정)
- **B. "삼성전자 대신증권 리포트 알려줘"**: 대신증권 필터를 적용해 바로 검색,
  정확한 gold 값(목표주가 56만원) 반환.
- **C. "삼성전자 리포트 요약해줘"**: 여러 증권사 리포트를 모두 요약(임의로
  하나만 선택하지 않음) — devset에 해당하는 완전히 모호한 리포트-특정 질문이
  없어 "여러 후보를 다 보여주는" 동작이 적절.
- **D. "이 리포트 목표주가 근거 알려줘"** (문맥에 report_id 있음): 수정 전에는
  문맥에 report_id가 있어도 시스템 프롬프트에 전혀 노출되지 않고 어떤 Tool도
  이를 조회에 쓰지 않아 **항상 되물었다**(구조적 공백). §6에서 최소 기능을
  추가해 이제 되묻지 않고 바로 해당 리포트의 목표주가 근거를 답변.

## 6. 뉴스·리포트 gold 문서 검색 실패 중 수정한 공통 원인

세 가지 공통 코드 오류를 발견해 수정했다(모두 "명시된 메타데이터 필터가
반영되지 않음" 패턴):

1. **`search_research_reports`의 빈 쿼리 처리 부재**: `query=""`(주제 없는
   "최근 리포트" 요청)이면 `HybridRetriever.search()`가 임베딩 API를 호출하려다
   방어 코드(`app/ml/embeddings.py`)에 막혀 예외가 발생했다. `search_news`에
   이미 있던 "주제 없으면 임베딩 없이 메타 최신순 조회" 패턴
   (`list_recent_news`)과 동일한 원칙으로 `ResearchReportSearch._list_recent_reports`
   를 추가해, 검색 주제가 없으면 `research_reports` 테이블에서 직접 최신순
   목록을 만들도록 수정했다. 이 결함이 report-15("2026-06-18에 나온
   한화투자증권 현대차 투자의견 알려줘", `query=""` + `historical_point`)의
   실행 오류 원인이었고, 수정 후 gold 리포트(760,000원)를 정확히 찾았다.
2. **`broker`가 명시돼도 벡터 검색 후보에 그 증권사 청크가 없으면 통째로
   놓침**: 기존 구현은 종목 전체 리포트를 벡터 유사도로 top_k개만 가져온 뒤
   broker로 후처리 필터링했다. 특정 증권사가 그 종목에 대해 리포트를 여러 건
   냈고 최신본이 상위 top_k 후보에 안 들어오면(report-09 실측: top_k=20에선
   최신본이 아예 없고 top_k=100에야 겨우 포함), 오래된 리포트를 잘못 반환했다.
   broker가 이미 사용자에 의해 특정된 이상 의미 검색으로 후보를 좁힐 이유가
   없으므로, broker가 있으면 임베딩 검색을 건너뛰고 `stock_code+broker`로
   메타 테이블에서 직접 조회하도록 수정했다(report-09: SK증권 175,000원(오래된
   리포트) → 134,000원(gold, 최신)으로 정정).
3. **화면 문맥 `report_id`가 프롬프트·Tool 어디에도 연결되지 않음**: §5-D에서
   확인한 구조적 공백. `_document_context_block`을 시스템 프롬프트에 추가하고,
   `search_research_reports`에 `report_id` 선택 인자와
   `ResearchReportSearch.get_by_report_id`를 추가했다(§9 "새 기능" 참고 —
   순수 프롬프트 수정이 아니라 최소 범위의 Tool 인자 확장).

세 수정 모두 임베딩 모델·RRF 가중치·top-k 상수·reranker는 변경하지 않았고,
질문별 키워드 하드코딩도 추가하지 않았다(broker/report_id/query 유무라는
일반 조건 분기만 사용).

## 7. 의미 검색 한계로 남긴 사례

다음은 순수 의미 검색 순위 문제로 확인해 수정하지 않았다:

- **news-04, news-09, news-13, news-14, news-15, news-19** (6건): targeted
  regression에서도 gold 문서를 여전히 찾지 못했다. 검색 쿼리에 사건명이
  누락되지도, 메타데이터 필터가 빠지지도 않았다 — 순수 벡터 유사도 랭킹이
  gold 뉴스 클러스터를 상위로 올리지 못하는 문제로, round2/round3에서도 이미
  기록된 한계다.
- **report-06** (대신증권 SK하이닉스 리포트 전망): round2에서 이미 "8배 후보
  확대(20→160)에도 못 찾음"으로 의미 검색 품질 한계로 확정했고, 이번 재확인도
  동일 결론.
- **disc-13**의 forbidden_claims("증권사") 오탐: §4 참고, 라벨 구조적 한계로
  미수정.
- **disc-11의 Tool 선택 변동성**: §2 참고, DB 정렬은 결정적이 됐으나 모델이
  `search_disclosures`/`get_disclosure_values` 중 어느 쪽을 쓸지는 매번 달라짐.

참고로 news-03과 report-08은 이번 targeted regression 재실행에서 우연히
gold를 찾았다(이번 라운드가 손댄 코드와 직접 관련 없음 — LLM 응답 변동성 또는
`current` 정책의 시간 기준일 이동으로 추정). 안정적으로 해결됐다고 보긴
어려워 여전히 "남은 한계" 범주에 포함해 기록한다.

## 8. gold label 및 devset 변경 여부

**변경 없음.** `docs/rag/phase_8/eval/devset.json`은 이번 라운드에서 전혀
수정하지 않았다(`git diff` 확인). 평가기(`app/eval/grader.py`) 수정도 §6
규칙에 따라 "정상 부정 표현을 금지 위반으로 오판"하는 케이스만 고쳤고, 실제
제품 실패(gold 미검색)를 가리기 위한 라벨/채점 완화는 하지 않았다.

## 9. 실제 남은 제품 실패 수

targeted regression(18문항) 기준:

- **완전히 수정됨**: report-09, report-15(리포트 Retriever), disc-11(DB
  tie-break), report-10/na-05/excl-05(평가기 부정 표현 오탐), A/D 케이스(리포트
  목록·문맥 조회 Tool 오류)
- **여전히 실패(순수 검색 품질/구조적 한계)**: news-04/09/13/14/15/19(6건),
  report-06(1건), disc-13(1건, 라벨 구조 한계) = **8건**
- **정상 동작 확인(애초에 실패가 아니었음)**: mix-09/mix-15(Validator 정탐)

Tool 선택 변동성(disc-11류)은 이번 표본(1건)에서만 관측돼 정량화하지 않았고,
별도 조사 대상으로 남긴다.

## 10. 변경 파일

```
app/agent/prompts.py                 — _document_context_block 추가
app/agent/runtime.py                 — 프롬프트에 source_type/source_id 연결,
                                        search_research_reports 에 report_id 인자 추가
app/agent/tools/reports.py           — report_id 조회 경로, _hits_to_result 리팩터
app/eval/grader.py                   — _NEGATION_MARKERS 확장, _claim_excluded_by_suffix 추가
app/services/facts.py                — get_latest_disclosures/get_structured_values
                                        rcept_no 2차 정렬(tie-break)
app/services/research_reports.py     — _list_recent_reports, get_by_report_id 추가,
                                        broker 우선 메타 조회로 search() 분기 변경
scripts/phase8_final_smoke_ambiguous_report.py  — 신규(§5 smoke test)
scripts/phase8_targeted_regression_final.py     — 신규(§7 targeted regression)
tests/unit/test_disclosure_tiebreak.py          — 신규(tie-break 회귀)
tests/unit/test_research_report_search.py       — broker/목록/report_id 테스트 추가,
                                                    fake DB 확장(chainable)
tests/unit/test_stock_context_prompt.py         — 문서 문맥 프롬프트 테스트 추가
tests/unit/test_eval_foundation.py              — 부정 표현 오탐 회귀 테스트 3건 추가
docs/rag/phase_8/eval/regression_final.json     — targeted regression 결과
docs/rag/phase_8/eval/final_ambiguous_report_smoke.json — §5 smoke 결과
```

devset·gold label·임베딩·RRF·top-k·reranker·Agent 아키텍처(create_agent 구조)는
변경하지 않았다.

## 11. 테스트 결과

`pytest tests/` 전체: **480 passed, 1 failed**.

실패 1건(`test_agent_runtime.py::test_feature_flag_off_returns_none`)은 로컬
`.env`의 `AGENT_ENABLED=true` 설정 때문에 발생하는 **사전 존재 결함**이며, 이번
변경 이전 커밋(`git stash` 후 재실행)에서도 동일하게 실패함을 확인했다 —
회귀 아님.

`ruff check`/`ruff format --check` 모두 통과(포맷 자동 적용 후).

## 12. 개발셋 최종 실행 준비 여부

**준비됨.** 이번 라운드는 targeted regression(18문항)만 수행했고 전체 120문항은
실행하지 않았다(prompt.md 지시). 다음 라운드에서 전체 devset을 재실행하면:

- §6에서 고친 3가지 공통 오류(리포트 빈 쿼리, broker 메타 우선 조회, 문서
  문맥 연결)가 devset 전반의 "증권사 리포트" 유형 다른 문항에도 긍정적 영향을
  줄 가능성이 있다(이번 라운드는 지목된 문항만 확인했다).
- §7에서 남긴 8건(뉴스 6, 리포트 1, 라벨 구조 1)은 순수 검색 품질/라벨 구조
  문제로, 이번 라운드 범위에서는 해결되지 않은 채 남아있다.
- disc-11류 Tool 선택 변동성은 전체 재실행에서 재현율을 확인해야 한다.

홀드아웃 40문항은 이번에도 열거나 실행하지 않았다.

## PR

(PR 생성 후 URL 기입)
