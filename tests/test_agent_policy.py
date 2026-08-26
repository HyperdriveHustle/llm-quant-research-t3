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
