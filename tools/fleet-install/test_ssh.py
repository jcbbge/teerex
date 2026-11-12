#!/usr/bin/env python3
"""Opt-in disposable loopback SSH acceptance. Requires sudo -n and /usr/sbin/sshd.

Generated keys exist only in temporary storage. No personal SSH config/keys are used.
Other acceptance tests can reuse `with loopback_ssh() as (ssh_fields, trusted, wrong)`;
ssh_fields are the shared address/port/identity_file/known_hosts/transport fields.
The trust file starts trusted; trusted/wrong are fixture public-host-key lines.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import socket
import subprocess
import tempfile
import time

import fleet_install as fleet
import test_fleet_install
from test_fleet_install import OLD, NEW, PLATFORM


@contextmanager
def loopback_ssh():
    """Run one bounded test's real SSH endpoint; always stop it and discard its keys."""
    username = pwd.getpwuid(os.getuid()).pw_name
    with tempfile.TemporaryDirectory(prefix="teerex-ssh-auth-") as temporary:
        temporary = Path(temporary).resolve()
        key, hostkey = temporary / "client-key", temporary / "host-key"
        for path in (key, hostkey):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
        (temporary / "authorized_keys").write_bytes(key.with_suffix(".pub").read_bytes())
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = temporary / "sshd_config"
        config.write_text(f"""Port {port}
ListenAddress 127.0.0.1
HostKey {hostkey}
PidFile {temporary}/sshd.pid
AuthorizedKeysFile {temporary}/authorized_keys
StrictModes no
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM yes
AllowUsers {username}
LogLevel ERROR
""")
        log = temporary / "sshd.log"
        log.touch()
        process = subprocess.Popen(["sudo", "-n", "/usr/sbin/sshd", "-D", "-f", str(config), "-E", str(log)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            for attempt in range(100):
                if process.poll() is not None:
                    raise RuntimeError("sshd exited: " + log.read_text() + process.stderr.read().decode())
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError("sshd readiness timeout: " + log.read_text())
            known = temporary / "known hosts with spaces"
            trusted = "[127.0.0.1]:" + str(port) + " " + hostkey.with_suffix(".pub").read_text()
            wrong = "[127.0.0.1]:" + str(port) + " " + key.with_suffix(".pub").read_text()
            known.write_text(trusted)
            yield dict(transport="ssh", address=username + "@127.0.0.1", port=port,
                       identity_file=str(key), known_hosts=str(known)), trusted, wrong
        finally:
            pidfile = temporary / "sshd.pid"
            if process.poll() is None and pidfile.exists():
                subprocess.run(["sudo", "-n", "kill", str(int(pidfile.read_text()))], check=True)
            process.wait(timeout=15)
            process.stderr.close()


def main():
    home = Path.home().resolve()
    username = pwd.getpwuid(os.getuid()).pw_name
    test_fleet_install.FleetContract.setUpClass()
    fixture = test_fleet_install.FleetContract()
    fixture.setUp()
    try:
        with loopback_ssh() as (ssh_fields, trusted, wrong), tempfile.TemporaryDirectory(prefix=".teerex-ssh-test-", dir=home) as installation:
            installation = Path(installation).resolve()
            host = dict(name="disposable-loopback", host_id="disposable-loopback", **ssh_fields,
                        home=str(home), platform=PLATFORM, teerex=str(installation / "bin/teerex"),
                        rex=str(installation / "unused-rex"), socket=str(installation / "unused.sock"),
                        store=str(installation / "unused-store"),
                        install=dict(prefix=str(installation / "managed"), expected_hostname=platform.node(), expected_user=username))
            known = Path(ssh_fields["known_hosts"])

            def call(version=OLD, **options):
                return fleet.run_fleet([host], dict(version=version, source=fixture.source, **options))

            known.write_text("")
            refused = call(apply=True)
            assert not refused["ok"] and not refused["applied"], refused
            assert refused["hosts"][0]["exit_code"] == 255 and "Host key verification failed" in refused["hosts"][0]["stderr"], refused
            assert not (installation / "managed").exists()
            known.write_text(trusted)
            first = call(apply=True)
            assert first["ok"], first
            assert first["hosts"][0]["verified_version"] == "teerex " + OLD[1:]
            assert first["hosts"][0]["verified_installation"]["sha256"] == hashlib.sha256(fixture.binaries[OLD]).hexdigest()
            upgraded = call(NEW, apply=True)
            assert upgraded["ok"], upgraded
            rolled = call(OLD, operation="rollback", apply=True)
            assert rolled["ok"], rolled
            host["install"]["expected_hostname"] = "not-this-host.invalid"
            mismatch = call(NEW, apply=True)
            assert not mismatch["ok"] and not mismatch["applied"], mismatch
            assert os.readlink(installation / "managed/current") == "versions/" + OLD
            host["install"]["expected_hostname"] = platform.node()
            known.write_text(wrong)
            changed = call(NEW, apply=True)
            assert not changed["ok"] and not changed["applied"], changed
            assert changed["hosts"][0]["exit_code"] == 255 and "Host key verification failed" in changed["hosts"][0]["stderr"], changed
            assert os.readlink(installation / "managed/current") == "versions/" + OLD
            print(json.dumps(dict(ok=True, platform=PLATFORM, transport="real_loopback_OpenSSH",
                                  checks=["unknown-host-key-refused", "strict-pinned-key-install", "known-hosts-path-with-spaces",
                                          "native-version-sha256", "upgrade", "retained-rollback", "hostname-mismatch-refused",
                                          "changed-host-key-refused"], personal_hosts_contacted=False)))
    finally:
        fixture.tearDown()
        fixture.doCleanups()
        test_fleet_install.FleetContract.tearDownClass()


if __name__ == "__main__":
    main()
