from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import TaskSessionStore  # noqa: E402


class TaskSessionStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.run_id = "run_test"
        ledger = self.root / "trajectories" / self.run_id / "agent" / "ledger.jsonl"
        ledger.parent.mkdir(parents=True)
        events = [
            {
                "sequence": 1,
                "state_version": 1,
                "event_type": "bootstrap",
                "timestamp": 100.0,
                "payload": {"factors": []},
            },
            {
                "sequence": 2,
                "state_version": 2,
                "event_type": "evaluate",
                "timestamp": 110.0,
                "payload": {
                    "action_id": "a1",
                    "response_id": "response_1",
                    "usage": {"model_calls": 1, "logical_tokens": 30},
                    "model_action": {"action": "evaluate", "arguments": {}},
                    "experiments": [
                        {
                            "factor_id": "factor_1",
                            "window_alias": "search_full",
                            "success": True,
                            "metrics": {"ic": 0.02, "rank_ic": 0.01},
                        }
                    ],
                    "observation": {"status": "ok"},
                },
            },
        ]
        ledger.write_text(
            "\n".join(json.dumps(event) for event in events) + "\n",
            encoding="utf-8",
        )
        logs = self.root / "runs" / self.run_id / "model_calls"
        logs.mkdir(parents=True)
        (logs / "call.json").write_text(
            json.dumps(
                {
                    "response_id": "response_1",
                    "model": "glm-5.3",
                    "system_prompt": "system",
                    "prompt": '{"state":1}',
                    "response_text": '{"action":"evaluate"}',
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "elapsed_seconds": 2.5,
                    "api_key": "must-not-render",
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_indexes_events_and_usage(self) -> None:
        store = TaskSessionStore(self.root, self.run_id)
        payload = store.index_payload()

        self.assertEqual(payload["event_count"], 2)
        self.assertEqual(payload["model_calls"], 1)
        self.assertEqual(payload["logical_tokens"], 30)
        self.assertEqual(payload["factor_evaluations"], 1)
        self.assertTrue(payload["events"][1]["has_model_call"])

    def test_combines_messages_action_and_harness_observation(self) -> None:
        store = TaskSessionStore(self.root, self.run_id)
        payload = store.read_event(2)

        self.assertEqual([message["role"] for message in payload["messages"]], [
            "system",
            "user",
            "assistant",
        ])
        self.assertEqual(payload["model_action"]["action"], "evaluate")
        self.assertEqual(payload["experiments"][0]["metrics"]["ic"], 0.02)
        self.assertEqual(payload["model_call"]["api_key"], "[REDACTED]")

    def test_reloads_appended_events(self) -> None:
        store = TaskSessionStore(self.root, self.run_id)
        with store.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "sequence": 3,
                        "state_version": 3,
                        "event_type": "checkpoint",
                        "timestamp": 120.0,
                        "payload": {},
                    }
                )
                + "\n"
            )

        self.assertEqual(store.index_payload()["event_count"], 3)


if __name__ == "__main__":
    unittest.main()
