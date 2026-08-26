from types import SimpleNamespace

from quant_harness.agent_policy import GLMAgentPolicy, ScriptedPolicy


def test_scripted_policy_preserves_action_order():
    policy = ScriptedPolicy(
        [
            {"action": "propose"},
            {"action": "stop"},
        ]
    )
    assert '"propose"' in policy.next_action({}).action_text
    assert '"stop"' in policy.next_action({}).action_text


def test_glm_policy_propagates_transport_attempt_count():
    class FakeClient:
        def __init__(self):
            self.kwargs = None

        def generate(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                text='{"action":"stop"}',
                input_tokens=10,
                output_tokens=5,
                attempts=2,
                response_id="response_1",
                status="completed",
                incomplete_reason=None,
            )

    client = FakeClient()
    turn = GLMAgentPolicy(
        client,
        temperature=0.2,
        max_output_tokens=65536,
    ).next_action({"state": "test"})

    assert turn.usage.logical_tokens == 15
    assert turn.usage.model_calls == 2
    assert client.kwargs["max_output_tokens"] == 65536


def test_glm_policy_uses_low_thinking_fallback_after_incomplete_output():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def generate(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(
                    text='{"',
                    input_tokens=100,
                    output_tokens=65536,
                    attempts=1,
                    response_id="deep",
                    status="incomplete",
                    incomplete_reason="length",
                )
            return SimpleNamespace(
                text='{"action":"stop"}',
                input_tokens=100,
                output_tokens=1000,
                attempts=1,
                response_id="fallback",
                status="completed",
                incomplete_reason=None,
            )

    client = FakeClient()
    policy = GLMAgentPolicy(
        client,
        temperature=0.3,
        max_output_tokens=65536,
        action_schema={"type": "object"},
        fallback_max_output_tokens=8192,
        fallback_enabled=True,
    )

    turn = policy.next_action({"state": "test"})

    assert turn.serialization_fallback_used is True
    assert turn.output_limit_hit is False
    assert turn.usage.model_calls == 2
    assert turn.usage.logical_tokens == 66736
    assert client.calls[1]["thinking"] == {"type": "disabled"}
    assert client.calls[1]["temperature"] == 0.0
    assert client.calls[1]["max_output_tokens"] == 8192
