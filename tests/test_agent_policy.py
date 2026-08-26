from quant_harness.agent_policy import ScriptedPolicy


def test_scripted_policy_preserves_action_order():
    policy = ScriptedPolicy(
        [
            {"action": "propose"},
            {"action": "stop"},
        ]
    )
    assert '"propose"' in policy.next_action({}).action_text
    assert '"stop"' in policy.next_action({}).action_text
