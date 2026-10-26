"""mcptoll test suite - real subprocess probes, estimators, config, CLI, exit codes."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")

sys.path.insert(0, SRC)

from mcptoll import __version__, estimate_tokens, estimate_tools  # noqa: E402
from mcptoll.config import load_config  # noqa: E402
from mcptoll.estimate import evaluate_flags, verdict_for  # noqa: E402
from mcptoll.probe import probe_stdio  # noqa: E402


def fixture_server_record(name, script):
    return {
        "name": name,
        "transport": "stdio",
        "command": sys.executable,
        "args": [os.path.join(FIXTURES, script)],
        "env": {},
        "url": None,
        "disabled": False,
    }


class TestEstimator(unittest.TestCase):
    def test_tokens_empty_and_floor(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens("a"), 1)
        self.assertEqual(estimate_tokens("x" * 400), 100)
        self.assertEqual(estimate_tokens("x" * 401), 101)

    def test_estimate_tools_records(self):
        tools = [
            {"name": "a", "description": "do a", "inputSchema": {"type": "object"}},
        ]
        recs = estimate_tools(tools)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["name"], "a")
        self.assertGreater(recs[0]["tokens"], 0)
        self.assertGreaterEqual(recs[0]["tokens"], recs[0]["schema_tokens"])

    def test_estimate_tools_empty(self):
        self.assertEqual(estimate_tools([]), [])
        self.assertEqual(estimate_tools(None), [])

    def test_verdict_thresholds(self):
        self.assertEqual(verdict_for(0), "LEAN")
        self.assertEqual(verdict_for(9.9), "LEAN")
        self.assertEqual(verdict_for(10), "OK")
        self.assertEqual(verdict_for(24.9), "OK")
        self.assertEqual(verdict_for(25), "FAT")
        self.assertEqual(verdict_for(49.9), "FAT")
        self.assertEqual(verdict_for(50), "BLOAT")

    def test_flags_duplicate_and_overload(self):
        reports = [
            {"server": "mini", "status": "ok",
             "tool_records": [{"name": "ping", "tokens": 10, "description_tokens": 2,
                               "schema_tokens": 5, "description_chars": 8}]},
            {"server": "bloat", "status": "ok",
             "tool_records": [{"name": "ping", "tokens": 10, "description_tokens": 2,
                               "schema_tokens": 5, "description_chars": 8}]
             + [{"name": "tool_%02d" % i, "tokens": 5, "description_tokens": 2,
                 "schema_tokens": 2, "description_chars": 10} for i in range(24)]},
        ]
        summary = evaluate_flags(reports, budget=1000)
        flags = " || ".join(summary["flags"])
        self.assertIn("DUPLICATE_TOOL:ping", flags)
        self.assertIn("TOOL_OVERLOAD:bloat", flags)
        self.assertEqual(summary["total_tools"], 26)
        self.assertEqual(summary["budget_pct"], 14.0)  # 140 of 1000
        self.assertEqual(summary["verdict"], "OK")

    def test_flags_unprobed(self):
        reports = [{"server": "remote", "status": "not-probed", "tool_records": []}]
        summary = evaluate_flags(reports, budget=100000)
        self.assertTrue(any(f.startswith("UNPROBED:remote") for f in summary["flags"]))

    def test_fat_description_and_heavy_schema(self):
        reports = [
            {"server": "s", "status": "ok",
             "tool_records": [
                 {"name": "novel", "tokens": 900, "description_tokens": 880,
                  "schema_tokens": 8, "description_chars": 4000},
                 {"name": "big", "tokens": 350, "description_tokens": 10,
                  "schema_tokens": 400, "description_chars": 40},
             ]},
        ]
        flags = " || ".join(evaluate_flags(reports, budget=10000)["flags"])
        self.assertIn("FAT_DESCRIPTION:s:novel", flags)
        self.assertIn("HEAVY_SCHEMA:s:big", flags)


class TestConfig(unittest.TestCase):
    def _write(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh)
        self.addCleanup(os.unlink, path)
        return path

    def test_claude_code_shape(self):
        path = self._write({"mcpServers": {
            "mini": {"command": "python3", "args": ["mini.py"]},
        }})
        cfg = load_config(path, environ={})
        self.assertEqual(cfg["client"], "generic")
        self.assertEqual(len(cfg["servers"]), 1)
        self.assertEqual(cfg["servers"][0]["transport"], "stdio")
        self.assertEqual(cfg["servers"][0]["args"], ["mini.py"])

    def test_http_transport(self):
        path = self._write({"mcpServers": {
            "remote": {"url": "https://example.tld/mcp"},
        }})
        cfg = load_config(path, environ={})
        self.assertEqual(cfg["servers"][0]["transport"], "http")

    def test_invalid_entry_flagged(self):
        path = self._write({"mcpServers": {"broken": {}}})
        cfg = load_config(path, environ={})
        self.assertEqual(cfg["servers"][0]["transport"], "invalid")

    def test_env_expansion(self):
        path = self._write({"mcpServers": {
            "mini": {"command": "python3", "args": ["${HOME:-/tmp}/srv.py"],
                     "env": {"KEY": "${MY_TOKEN}"}},
        }})
        cfg = load_config(path, environ={"MY_TOKEN": "sekrit", "HOME": "/home/x"})
        self.assertEqual(cfg["servers"][0]["args"], ["/home/x/srv.py"])
        self.assertEqual(cfg["servers"][0]["env"], {"KEY": "sekrit"})

    def test_env_expansion_default(self):
        path = self._write({"mcpServers": {
            "mini": {"command": "python3", "args": ["${MISSING_VAR:-fallback}"]},
        }})
        cfg = load_config(path, environ={})
        self.assertEqual(cfg["servers"][0]["args"], ["fallback"])

    def test_bad_shape_raises(self):
        path = self._write({"not_mcp": True})
        with self.assertRaises(ValueError):
            load_config(path, environ={})

    def test_empty_config_ok(self):
        path = self._write({})
        cfg = load_config(path, environ={})
        self.assertEqual(cfg["servers"], [])


class TestProbeStdio(unittest.TestCase):
    def test_mini_server_handshake(self):
        report = probe_stdio(fixture_server_record("mini", "mini_server.py"), timeout=10)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(sorted(t["name"] for t in report["tools"]),
                         ["add", "echo", "ping"])

    def test_bloat_server_handshake(self):
        report = probe_stdio(fixture_server_record("bloat", "bloat_server.py"), timeout=10)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(len(report["tools"]), 26)
        self.assertIn("everything", [t["name"] for t in report["tools"]])
        recs = estimate_tools(report["tools"])
        self.assertEqual(recs[0]["name"], "tool_00")

    def test_missing_binary_error(self):
        server = fixture_server_record("ghost", "missing.py")
        server["command"] = "/nonexistent/binary/nowhere"
        report = probe_stdio(server, timeout=5)
        self.assertEqual(report["status"], "error")
        self.assertIn("failed to spawn", report["error"])

    def test_http_not_probed(self):
        server = {"name": "remote", "transport": "http", "command": None,
                  "args": [], "env": {}, "url": "https://x.tld/mcp"}
        report = probe_stdio(server, timeout=5)
        self.assertEqual(report["status"], "not-probed")
        self.assertIn("http/remote", report["error"])


class TestEndToEndCli(unittest.TestCase):
    def _config_file(self, servers):
        fd, path = tempfile.mkstemp(suffix="_mcp.json")
        payload = {"mcpServers": servers}
        with os.fdopen(fd, "w") as fh:
            json.dump(payload, fh)
        self.addCleanup(os.unlink, path)
        return path

    def _run(self, *argv):
        env = dict(os.environ)
        proc = subprocess.run(
            [sys.executable, "-m", "mcptoll.cli"] + list(argv),
            capture_output=True, text=True, env=env, timeout=60,
            cwd=ROOT,
        )
        return proc

    def test_lean_config_exit_zero(self):
        path = self._config_file(
            {"mini": {"command": sys.executable,
                      "args": [os.path.join(FIXTURES, "mini_server.py")]}}
        )
        proc = self._run(path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("VERDICT: LEAN", proc.stdout)
        self.assertIn("mini", proc.stdout)
        self.assertIn("TOTAL:", proc.stdout)

    def test_bloat_config_exit_one(self):
        # both servers in one config so `ping` is a true cross-server duplicate
        path = self._config_file(
            {"mini": {"command": sys.executable,
                      "args": [os.path.join(FIXTURES, "mini_server.py")]},
             "bloat": {"command": sys.executable,
                       "args": [os.path.join(FIXTURES, "bloat_server.py")]}}
        )
        proc = self._run(path, "--budget", "2000")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("TOOL_OVERLOAD:bloat", proc.stdout)
        self.assertIn("DUPLICATE_TOOL", proc.stdout)
        self.assertIn("cut-list", proc.stdout)
        self.assertIn("FAT_DESCRIPTION", proc.stdout)
        self.assertIn("HEAVY_SCHEMA", proc.stdout)

    def test_json_mode(self):
        path = self._config_file(
            {"mini": {"command": sys.executable,
                      "args": [os.path.join(FIXTURES, "mini_server.py")]}}
        )
        proc = self._run(path, "--json")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        data = json.loads(proc.stdout)
        cfg = data["configs"][0]
        self.assertEqual(cfg["servers"][0]["server"], "mini")
        self.assertEqual(cfg["summary"]["verdict"], "LEAN")

    def test_probe_error_exit_two(self):
        path = self._config_file(
            {"dead": {"command": "/nonexistent/binary/nowhere", "args": []}}
        )
        proc = self._run(path)
        self.assertEqual(proc.returncode, 2)

    def test_adhoc_cmd(self):
        proc = self._run(
            "--cmd", "%s %s" % (sys.executable, os.path.join(FIXTURES, "mini_server.py"))
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("ad-hoc", proc.stdout)

    def test_cli_script_importable(self):
        from mcptoll.cli import build_parser, main
        self.assertEqual(build_parser().prog, "mcptoll")
        self.assertEqual(main([]), 2)  # no configs found in ROOT, no error thrown
        self.assertEqual(__version__, "1.0.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
