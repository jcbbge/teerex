"""Opt-in physical two-host acceptance. Only disposable Rex, synthetic agent, private temp dirs.

Run on the pane host with TEEREX_COMPUTE_HOST, TEEREX_COMPUTE_BIN,
TEEREX_COMPUTE_PYTHON and TEEREX_HOSTS_CONFIG. Reverse route comes from the
compute host's same config path (override TEEREX_COMPUTE_HOSTS_CONFIG).
This test copies only its fixture/config to a tool-host temporary directory.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import unittest
from test_agents import AgentsTest, BIN, FIXTURE, events, wait_for


@unittest.skipUnless(os.environ.get("TEEREX_COMPUTE_HOST"), "opt-in physical compute host")
class PhysicalComputeTest(AgentsTest):
    def test_physical_compute_ack_literal_argv_brief_and_measured_exit(self):
        remote = os.environ["TEEREX_COMPUTE_HOST"]
        config_path = os.environ["TEEREX_HOSTS_CONFIG"]
        route = json.loads(Path(config_path).read_text())["hosts"][remote]
        def ssh(command, stdin=None):
            return subprocess.check_output(["ssh", remote, command], input=stdin, timeout=30)
        work = ssh("mktemp -d /tmp/teerex-compute.XXXXXX").decode().strip()
        self.addCleanup(lambda: ssh("rm -rf -- " + shlex.quote(work)))
        # Existing SSH credential paths are referenced, never copied or read.
        reverse_path = os.environ.get("TEEREX_COMPUTE_HOSTS_CONFIG", config_path)
        reverse_name = os.environ["TEEREX_PANE_HOST"]
        reverse = json.loads(ssh("cat " + shlex.quote(reverse_path)))["hosts"][reverse_name]
        remote_bin = os.environ["TEEREX_COMPUTE_BIN"]
        remote_python = os.environ["TEEREX_COMPUTE_PYTHON"]
        def put(name, data):
            path = work + "/" + name
            ssh("cat > " + shlex.quote(path), data.encode())
            return path
        put("fixture.py", FIXTURE)
        wrapper = put("teerex", "#!/bin/sh\nexport HOME=" + shlex.quote(work) + "\nexport TEEREX_CALL_LOG_DIR=" + shlex.quote(work + "/calls") + "\nexec " + shlex.quote(remote_bin) + ' "$@"\n')
        ssh("chmod 700 " + shlex.quote(wrapper))
        local_wrapper = self.work / "teerex"
        local_wrapper.write_text("#!/bin/sh\nexport HOME=" + shlex.quote(str(self.root)) + "\nexport TEEREX_CALL_LOG_DIR=" + shlex.quote(str(self.work / "calls")) + "\nexec " + shlex.quote(BIN) + ' "$@"\n')
        local_wrapper.chmod(0o700)
        reverse.update(socket=str(self.socket), teerex=str(local_wrapper), store=str(self.work / "boards"), host_id="disposable")
        callbacks = put("callbacks.json", json.dumps(dict(schema_version=1, hosts=dict(pane=reverse))))
        route.update(teerex=wrapper, socket="/tmp/unused-compute.sock", store=work + "/boards")
        targets = self.work / "targets.json"
        targets.write_text(json.dumps(dict(schema_version=1, hosts=dict(compute=route))))
        literal = ["", "two words", "line\nbreak", "'$;`\" β"]
        log = work + "/worker.jsonl"
        self.settings["profiles"]["probe"].update(argv=[remote_python, work + "/fixture.py", log, "exit7", *literal],
            standing_flags=[], execution=dict(config=str(targets), host="compute", cwd=work), callbacks=dict(config=callbacks, host="pane"))
        self.config.write_text(json.dumps(self.settings))
        p, receipt = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief), "--ack-timeout-ms", "15000", timeout=40)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        def finished():
            state = self.record(receipt["launch_id"])
            return state if state.get("remote_child_term") else None
        state = wait_for(finished, timeout=20)
        self.assertEqual(state["remote_child_term"], {"Exited": 7})
        data = [json.loads(line) for line in ssh("cat " + shlex.quote(log)).splitlines()]
        self.assertEqual(data[0]["argv"], literal)
        self.assertEqual([v["code"] for v in data if v["event"] == "ack"], [0])
        self.assertEqual([v["payload"] for v in data if v["event"] == "input"], ["FROM probe: " + self.brief.read_text()])
        self.assertFalse(data[0]["registry_present"])
        print("PHYSICAL COMPUTE PROVEN:", sys.platform, "pane ->", remote, "ACK, literal argv, one brief, measured exit 7", flush=True)


if __name__ == "__main__":
    unittest.main()
