from experiments.exp_b_factual_summaries import summarize


class FakeResponse:
    status_code = 200
    ok = True
    text = ""

    def __init__(self, content: str, finish_reason: str, tokens: int) -> None:
        self.content = content
        self.finish_reason = finish_reason
        self.tokens = tokens

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {"content": self.content},
                    "finish_reason": self.finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": self.tokens,
                "completion_tokens": self.tokens,
                "total_tokens": self.tokens * 2,
            },
        }


def test_call_solar_retries_invalid_json_with_compact_prompt(monkeypatch) -> None:
    responses = iter(
        [
            FakeResponse('{"title":"잘린 응답"', "length", 10),
            FakeResponse(
                '{"title":"제목","easy_explanation":"쉬운 설명이에요.",'
                '"factual_body":"**핵심 사실입니다.**\\n\\n배경 설명입니다."}',
                "stop",
                20,
            ),
        ]
    )
    payloads: list[dict] = []

    def fake_post(_url, *, headers, json, timeout):
        del headers, timeout
        payloads.append(json.copy() | {"messages": [item.copy() for item in json["messages"]]})
        return next(responses)

    monkeypatch.setattr(summarize.requests, "post", fake_post)
    monkeypatch.setattr(summarize.time, "sleep", lambda _seconds: None)

    parsed, meta = summarize.call_solar("key", "기사 입력", max_retries=2)

    assert parsed["title"] == "제목"
    assert meta["parse_success"] is True
    assert meta["request_count"] == 2
    assert meta["usage"]["total_tokens"] == 60
    assert payloads[1]["messages"][0]["content"] == summarize.COMPACT_RETRY_SYSTEM_PROMPT
    assert payloads[1]["max_tokens"] == 1100


def test_selection_explanation_is_requested_as_short_beginner_copy(monkeypatch) -> None:
    payloads: list[dict] = []

    def fake_post(_url, *, headers, json, timeout):
        del headers, timeout
        payloads.append(json)
        return FakeResponse(
            '{"explanation":"쉽게 말하면 로봇 사업을 한곳에서 이끄는 전담팀이에요.'
            '\\n\\n기술 개발부터 실제 사업 적용까지 맡아요."}',
            "stop",
            20,
        )

    monkeypatch.setattr(summarize.requests, "post", fake_post)

    parsed, meta = summarize.call_solar_easy_explain(
        "key",
        "RX사업추진실",
        "삼성전자가 대표이사 직속 조직을 신설했다.",
        max_retries=1,
    )

    assert meta["parse_success"] is True
    assert "\\n\\n" not in parsed["explanation"]
    assert "\n\n" in parsed["explanation"]
    assert payloads[0]["max_tokens"] == 240
    assert "최대 3문장, 180자 이내" in payloads[0]["messages"][0]["content"]
