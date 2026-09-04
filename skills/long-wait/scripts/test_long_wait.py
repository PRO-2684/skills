#!/usr/bin/env python3
"""Focused CLI checks for long_wait.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Dict, List, Optional


SCRIPT = Path(__file__).resolve().with_name("long_wait.py")
ID_A = "00000000-0000-4000-8000-000000000001"
ID_B = "00000000-0000-4000-8000-000000000002"
ID_C = "00000000-0000-4000-8000-000000000003"
ID_D = "00000000-0000-4000-8000-000000000004"


def record(
    wait_id: str,
    thread_id: str,
    kind: str = "after",
    state: str = "waiting",
    run_timeout: Optional[float] = 60.0,
    after_seconds: float = 3600.0,
) -> Dict[str, object]:
    specs: Dict[str, object] = {
        "probe": None,
        "after": {"seconds": after_seconds, "registered_at": time.time()},
        "run": {
            "command": ["echo", "hello world"],
            "timeout": run_timeout,
            "max_retries": 2,
            "retry_delay": 5.0,
        },
        "until": {
            "command": ["test", "-f", "/tmp/done"],
            "timeout": 120.0,
            "interval": 10.0,
        },
    }
    return {
        "id": wait_id,
        "thread_id": thread_id,
        "kind": kind,
        "spec": specs[kind],
        "message": "Continue work.",
        "delivery_assumption": "Local durable thread verified.",
        "state": state,
        "pid": None,
        "child_pid": None,
        "created_at": time.time(),
        "condition_at": None,
        "delivered_at": None,
        "log_path": "",
        "result": None,
        "error": None,
    }


class LongWaitCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.home = Path(self.temporary.name)
        self.store = self.home / "long-waits"
        self.store.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, value: Dict[str, object]) -> None:
        (self.store / f"{value['id']}.json").write_text(json.dumps(value))

    def run_cli(
        self,
        *args: str,
        thread_id: Optional[str] = "thread-a",
        check: bool = True,
        cwd: Optional[Path] = None,
        codex_bin: Optional[Path] = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(self.home)
        if codex_bin is not None:
            environment["CODEX_BIN"] = str(codex_bin)
            environment["FAKE_QUEUE_LOG"] = str(self.home / "queue.log")
        if thread_id is None:
            environment.pop("CODEX_THREAD_ID", None)
        else:
            environment["CODEX_THREAD_ID"] = thread_id
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            check=check,
            capture_output=True,
            text=True,
            env=environment,
            cwd=cwd,
        )

    def test_run_inherits_registration_cwd(self) -> None:
        task = self.home / "task"
        scripts = task / "scripts"
        scripts.mkdir(parents=True)
        predicate = scripts / "predicate.py"
        predicate.write_text(
            "#!/usr/bin/env python3\n"
            "import time\n"
            "from pathlib import Path\n"
            "time.sleep(0.2)\n"
            "Path('ran').touch()\n"
        )
        predicate.chmod(0o700)
        fake_codex = self.home / "codex"
        fake_codex.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  app-server)\n"
            "    while IFS= read -r request; do\n"
            '      case "$request" in\n'
            '        *\'"method":"initialize"\'*) printf \'%s\\n\' \'{"id":1,"result":{}}\' ;;\n'
            '        *\'"method":"thread/read"\'*) printf \'%s\\n\' \'{"id":2,"result":{"thread":{"ephemeral":false,"source":"cli"}}}\' ;;\n'
            "      esac\n"
            "    done\n"
            "    ;;\n"
            '  queue) printf \'%s\\n\' "$*" > "$FAKE_QUEUE_LOG" ;;\n'
            "esac\n"
        )
        fake_codex.chmod(0o700)

        registered = json.loads(
            self.run_cli(
                "run",
                "--json",
                "--timeout",
                "5s",
                "--description",
                "Run relative predicate",
                "--",
                "scripts/predicate.py",
                cwd=task,
                codex_bin=fake_codex,
            ).stdout
        )
        self.assertEqual(registered["description"], "Run relative predicate")
        deadline = time.time() + 5
        while not (task / "ran").exists() and time.time() < deadline:
            time.sleep(0.05)

        self.assertTrue((task / "ran").exists())
        record_path = self.store / f"{registered['id']}.json"
        while record_path.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(record_path.exists())
        self.assertIn(
            '"description":"Run relative predicate"',
            (self.home / "queue.log").read_text(),
        )

    def test_list_scopes_human_and_json_output(self) -> None:
        current = record(ID_A, "thread-a")
        current["created_at"] = time.time() - 65
        current["description"] = "Train baseline model"
        self.write(current)
        self.write(record(ID_B, "thread-b"))

        scoped = self.run_cli("list").stdout
        self.assertIn("Waits of current thread thread-a (1/2):", scoped)
        self.assertIn("AGE/LIMIT", scoped)
        self.assertIn("1m5s/1h", scoped)
        self.assertIn("DESCRIPTION", scoped)
        self.assertIn("Train baseline model", scoped)
        self.assertIn(ID_A, scoped)
        self.assertNotIn(ID_B, scoped)
        self.assertEqual(
            [item["id"] for item in json.loads(self.run_cli("list", "--json").stdout)],
            [ID_A],
        )

        all_human = self.run_cli("list", "--all").stdout
        self.assertIn("All waits on current machine (2):", all_human)
        self.assertIn(ID_A, all_human)
        self.assertIn(ID_B, all_human)
        self.assertEqual(
            len(json.loads(self.run_cli("list", "--all", "--json").stdout)), 2
        )
        self.assertIn(
            "All waits on current machine (2):",
            self.run_cli("list", thread_id=None).stdout,
        )

    def test_list_omits_limit_suffix_when_unset(self) -> None:
        self.write(record(ID_A, "thread-a", "run", run_timeout=None))

        row = self.run_cli("list").stdout.splitlines()[-1]
        self.assertNotIn("/", row)

    def test_list_shows_verbose_day_age(self) -> None:
        value = record(ID_A, "thread-a", after_seconds=172800.0)
        value["created_at"] = time.time() - 98700
        self.write(value)

        self.assertIn("1d3h25m/2d", self.run_cli("list").stdout)

    def test_description_is_full_in_status_and_compact_in_list(self) -> None:
        description = "A human-facing description that is deliberately longer than forty-eight characters"
        value = record(ID_A, "thread-a")
        value["description"] = description
        self.write(value)

        self.assertIn(
            f"Description: {description}", self.run_cli("status", ID_A).stdout
        )
        self.assertEqual(
            json.loads(self.run_cli("status", ID_A, "--json").stdout)["description"],
            description,
        )
        self.assertIn(description[:47] + "…", self.run_cli("list").stdout)

    def test_empty_list_retains_scope(self) -> None:
        self.assertEqual(
            self.run_cli("list").stdout,
            "Waits of current thread thread-a (0/0):\nNo waits.\n",
        )
        self.assertEqual(
            self.run_cli("list", thread_id=None).stdout,
            "All waits on current machine (0):\nNo waits.\n",
        )
        self.assertEqual(json.loads(self.run_cli("list", "--json").stdout), [])

    def test_record_kinds_render_human_and_json(self) -> None:
        for wait_id, kind in zip(
            (ID_A, ID_B, ID_C, ID_D), ("probe", "after", "run", "until")
        ):
            self.write(record(wait_id, "thread-a", kind))
            human = self.run_cli("status", wait_id).stdout
            self.assertIn("Wait status:", human)
            self.assertIn(f"Kind: {kind}", human)
            structured = json.loads(self.run_cli("status", wait_id, "--json").stdout)
            self.assertEqual(structured["kind"], kind)

        self.assertIn("Delay: 1h", self.run_cli("status", ID_B).stdout)
        self.assertIn(
            "Command: echo 'hello world'", self.run_cli("status", ID_C).stdout
        )
        self.assertIn(
            "Predicate: test -f /tmp/done", self.run_cli("status", ID_D).stdout
        )

    def test_json_round_trip_preserves_compact_result(self) -> None:
        value = record(ID_A, "thread-a", "run")
        result = {
            "kind": "run",
            "status": 0,
            "reason": "exited",
            "attempts": 1,
            "elapsed_seconds": 1.25,
        }
        value["result"] = result
        self.write(value)

        structured = json.loads(self.run_cli("status", ID_A, "--json").stdout)
        self.assertEqual(structured["result"], result)
        self.assertNotIn("child_pid", structured)

    def test_cancel_resolve_and_cleanup_render_human_and_json(self) -> None:
        self.write(record(ID_A, "thread-a"))
        self.assertEqual(
            self.run_cli("cancel", ID_A).stdout,
            f"Cancelled {ID_A}: state=cancelled.\n",
        )
        self.assertEqual(
            json.loads(self.run_cli("cancel", ID_A, "--json").stdout)["state"],
            "cancelled",
        )

        self.write(record(ID_B, "thread-a", state="delivery_unknown"))
        refused = self.run_cli("cancel", ID_B, check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("cannot cancel wait in state delivery_unknown", refused.stderr)
        resolved = self.run_cli("resolve", ID_B, "delivered").stdout
        self.assertEqual(resolved, f"Resolved (delivered) {ID_B}: state=delivered.\n")

        self.write(record(ID_C, "thread-a", state="delivery_unknown"))
        self.assertEqual(
            json.loads(self.run_cli("resolve", ID_C, "delivered", "--json").stdout)[
                "state"
            ],
            "delivered",
        )

        self.write(record(ID_D, "thread-a", state="failed"))
        (self.store / f"{ID_D}.log").write_text("failure\n")
        cleanup = self.run_cli("cleanup", ID_D).stdout
        self.assertIn(f"Removed: {ID_D}.json, {ID_D}.log", cleanup)
        self.assertEqual(self.run_cli("cleanup", ID_D).stdout, "Nothing to remove.\n")
        self.assertEqual(
            json.loads(self.run_cli("cleanup", ID_D, "--json").stdout)["removed"], []
        )

    def test_json_flag_is_accepted_by_registration_commands(self) -> None:
        commands: List[List[str]] = [
            ["probe", "--json"],
            ["after", "--json", "1h"],
            ["run", "--json", "--", "true"],
            ["until", "--json", "--timeout", "1s", "--", "true"],
        ]
        for command in commands:
            result = self.run_cli(*command, thread_id=None, check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("CODEX_THREAD_ID unavailable", result.stderr)
            self.assertNotIn("unrecognized arguments", result.stderr)


if __name__ == "__main__":
    unittest.main()
