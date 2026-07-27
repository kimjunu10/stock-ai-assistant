# Phase 9 수정 후 동일 홀드아웃 회귀 실패 원인표

이 문서는 최초 블라인드 홀드아웃 결과가 아니다. Phase 8에서 사용한 동일
40문항을 Phase 9 Tool runtime 수정 후 재사용한 회귀 테스트 결과다.

## Formal 실패

| 문항 | Tool 상태 | 동결 채점 실패 조건 | 직접 관찰 |
|---|---|---|---|
| h-fin-20 | `get_financial_facts=ok` | `financial_value_mismatch` | Tool은 `amount_type=cumulative`로 2025년 3분기 누적 영업이익 5,506.4억원을 반환했다. 동결 Gold는 `quarter` 137,059,000,000원이라 값 의미가 일치하지 않았다. |

formal 실패는 1건이다. 결과 확인 후 Gold·채점기·Tool·프롬프트를 변경하지 않았다.

## 실제 Tool·완료 실패

| 문항 | Tool trace | 최종 상태 | 내부 오류 기록 |
|---|---|---|---|
| h-na-09 | `get_financial_facts=null` 2회 후 `ok` 2회 | 답변 완료 | 잘못된 계정명 `순이익` 호출 2건은 recorder에 `null`로 남았다. `TOOL_RUNTIME_ERROR`가 생성되지 않아 예외 클래스, 실패 계층, correlation ID는 확인 불가다. 기대 request ID는 `eval-h-na-09`였다. |

실제 Tool 오류·상태 누락·`step_limit`·빈 답변 중 하나라도 있는 문항은
1건이다. Phase 8의 동일 정의 31건에서 30건 감소했다.

`h-na-09`는 이후 `당기순이익`으로 교정한 삼성전자·AAPL 호출이 모두
`status=ok`였고 최종 답변도 완료됐다. 하지만 앞선 상태 누락을 성공으로
숨기지 않고 실제 runtime 실패로 유지한다.

## 외부 장애

429, timeout, 명시적 네트워크 오류는 0건이었다. 문항 재시도도 0회다.
