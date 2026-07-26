"""LLM judge 채점 단위 테스트. 실제 API 호출 없음(judge 는 가짜로 주입).

검증 원칙:
- 객관적 지표(Tool·문서 ID·숫자·기간)는 judge 와 무관하게 항상 코드로 채점된다.
- 자연어 판정(제외 조건·답변 불가 처리)만 judge 결과를 쓴다.
- judge 가 없거나 호출 실패면 기존 키워드 채점으로 폴백한다.
"""

from __future__ import annotations

from app.eval.grader import grade_case
from app.eval.llm_judge import JudgeCache, JudgeVerdict, build_user_prompt
from app.eval.runner import RunRecord
from app.eval.schema import EvalCase


def _case(**kw) -> EvalCase:
    base = {
        "id": "t-1",
        "type": "뉴스 사건·영향",
        "question": "무슨 일 있었어?",
        "stock_code": "005930",
        "required_tools": ["search_news"],
    }
    base.update(kw)
    return EvalCase(**base)


def _record(**kw) -> RunRecord:
    base = {"case_id": "t-1", "question": "q", "context": {}, "stop_reason": "completed"}
    base.update(kw)
    return RunRecord(**base)


def _judge(verdict: JudgeVerdict):
    return lambda _case, _record: verdict


class TestExclusionJudging:
    def test_judge_overrides_keyword_false_positive(self):
        """금지어를 '거절하는 문장'에 쓴 경우, 키워드는 위반으로 잡지만 judge 는 통과."""
        case = _case(id="na-x", forbidden_claims=["추천"])
        rec = _record(case_id="na-x", answer="매수·매도 추천은 드리지 않습니다.")

        # 키워드 채점: '추천'이 문장에 있고 부정 표현 마커가 없어 위반으로 잡힌다.
        kw = grade_case(case, rec)
        assert kw.exclusion_violations == ["추천"]

        # judge 채점: 의미상 제외를 지켰으므로 위반 없음.
        judged = grade_case(
            case, rec, judge=_judge(JudgeVerdict(exclusion_respected=True, ok=True))
        )
        assert judged.exclusion_violations == []

    def test_judge_can_still_flag_real_violation(self):
        """judge 가 실제 위반이라고 하면 그대로 위반으로 집계한다."""
        case = _case(id="x", forbidden_claims=["목표주가"])
        rec = _record(case_id="x", answer="증권사 목표주가는 12만원입니다.")
        judged = grade_case(
            case,
            rec,
            judge=_judge(
                JudgeVerdict(exclusion_respected=False, reason="목표주가를 실제로 제시함", ok=True)
            ),
        )
        assert judged.exclusion_violations == ["목표주가"]
        assert any("judge 제외조건 위반" in n for n in judged.notes)

    def test_judge_failure_falls_back_to_keyword(self):
        """judge 호출이 실패하면(ok=False) 기존 키워드 채점을 그대로 쓴다."""
        case = _case(id="x", forbidden_claims=["추천"])
        rec = _record(case_id="x", answer="매수 추천은 드리지 않습니다.")
        judged = grade_case(case, rec, judge=_judge(JudgeVerdict(ok=False, error="http_500")))
        # 폴백했으므로 키워드 채점과 같은 결과가 나온다.
        assert judged.exclusion_violations == grade_case(case, rec).exclusion_violations


class TestUnanswerableJudging:
    def test_judge_overrides_keyword_on_unanswerable(self):
        """키워드에 없는 표현으로 올바르게 거절한 답변을 judge 는 통과 처리한다."""
        case = _case(
            id="na-y",
            type="답변 불가능·모호",
            is_answerable=False,
            no_data_expectation="데이터 없음을 밝혀야 한다",
        )
        rec = _record(
            case_id="na-y",
            answer="내년 매출 확정값은 아직 공시되지 않았습니다.",
            sources=[{"source_id": "s1", "source_type": "financial"}],
        )
        judged = grade_case(case, rec, judge=_judge(JudgeVerdict(handled_correctly=True, ok=True)))
        assert judged.unanswerable_handled is True

    def test_judge_can_fail_a_made_up_answer(self):
        case = _case(
            id="na-z",
            type="답변 불가능·모호",
            is_answerable=False,
            no_data_expectation="데이터 없음을 밝혀야 한다",
        )
        rec = _record(case_id="na-z", answer="내년 매출은 300조원입니다.")
        judged = grade_case(
            case,
            rec,
            judge=_judge(
                JudgeVerdict(handled_correctly=False, reason="근거 없이 값을 단정", ok=True)
            ),
        )
        assert judged.unanswerable_handled is False
        assert any("judge 답변불가 처리 실패" in n for n in judged.notes)

    def test_answerable_case_is_not_judged_for_unanswerable(self):
        """답변 가능한 질문은 judge 가 뭘 주든 unanswerable 판정 대상이 아니다."""
        case = _case(id="x")  # is_answerable 기본 True
        rec = _record(case_id="x", answer="삼성전자 영업이익은 43조원입니다.")
        judged = grade_case(case, rec, judge=_judge(JudgeVerdict(handled_correctly=False, ok=True)))
        assert judged.unanswerable_handled is None


class TestObjectiveMetricsUnaffected:
    def test_tool_and_number_grading_ignores_judge(self):
        """judge 가 어떤 값을 주든 Tool 호출·숫자 채점 결과는 바뀌지 않는다."""
        case = _case(
            id="x",
            required_tools=["search_news", "get_stock_prices"],
            expected_numbers=[{"label": "영업이익", "value": 1000.0, "unit": "원"}],
        )
        rec = _record(
            case_id="x",
            answer="영업이익은 1000원입니다.",
            tool_calls=[{"name": "search_news", "args": {}, "status": "ok", "latency_ms": 1}],
        )
        plain = grade_case(case, rec)
        with_judge = grade_case(
            case,
            rec,
            judge=_judge(JudgeVerdict(exclusion_respected=False, handled_correctly=False, ok=True)),
        )
        assert plain.passed_required_tools == with_judge.passed_required_tools is False
        assert plain.number_results == with_judge.number_results
        assert with_judge.number_results[0]["matched"] is True


class TestJudgeInputAndCache:
    def test_prompt_contains_question_answer_sources_only(self):
        """judge 입력에 gold 정답이 들어가지 않는다(근거 범위 판정용)."""
        prompt = build_user_prompt(
            question="영업이익 얼마야?",
            answer="43조원입니다.",
            sources=[
                {"source_type": "financial", "title": "영업이익 · 2025 연간", "publisher": None}
            ],
            is_answerable=True,
            forbidden_claims=[],
        )
        assert "영업이익 얼마야?" in prompt
        assert "43조원입니다." in prompt
        assert "financial" in prompt
        # 정답 라벨·gold 문서 ID 같은 표현이 새어 들어가지 않아야 한다.
        assert "gold" not in prompt.lower()

    def test_prompt_marks_unanswerable_and_exclusions(self):
        prompt = build_user_prompt(
            question="이 종목 사도 돼?",
            answer="추천은 드리지 않습니다.",
            sources=[],
            is_answerable=False,
            forbidden_claims=["추천", "사세요"],
        )
        assert "답할 수 없는 질문" in prompt
        assert "추천" in prompt and "사세요" in prompt
        assert "근거 없음" in prompt

    def test_cache_roundtrip(self, tmp_path):
        cache = JudgeCache(tmp_path / "c.json").load()
        assert len(cache) == 0
        cache.put("k1", JudgeVerdict(handled_correctly=True, ok=True).as_dict())
        cache.save()

        reloaded = JudgeCache(tmp_path / "c.json").load()
        assert len(reloaded) == 1
        assert reloaded.get("k1")["handled_correctly"] is True
        assert reloaded.get("missing") is None
