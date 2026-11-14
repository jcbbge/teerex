"""Read-only configured-host installation health."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys


class ActionParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n" + (f"next: {self.prog} --help\n" if (sys.stdin.isatty() and sys.stderr.isatty()) else ""))


def run_command(argv):
    result = subprocess.run(argv, capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def inspect_host(host):
    home = Path(host['home'])
    root = Path(host.get('rexconfig', str(home / 'rexconfig')))
    install = shlex.join([str(root / 'install')])
    checks = []

    def add(name, ok, detail, fix):
        checks.append(dict(check=name, ok=bool(ok), detail=detail, fix=fix))

    current = home / '.local/opt/teerex-managed/current'
    try:
        pin = (root / host['host_id'] / 'teerex/build-pin.txt').read_text().strip()
        actual = os.readlink(current)
        tag = pin[len('versions/'):] if pin.startswith('versions/') else pin
        installer = home / 'teerex/tools/install/teerex-install'
        operation = 'rollback' if (current.parent / 'versions' / tag).is_dir() else 'upgrade'
        add('teerex_build', pin == actual, f'installed {actual}; pinned {pin}',
            shlex.join(['bash', str(installer), operation, '--prefix', str(current.parent), '--version', tag]))
    except OSError as exc:
        add('teerex_build', False, str(exc), install)
    try:
        code, out, err = run_command([host['rex'], '--autostart=false', '--server', 'unix://' + host['socket'],
                                      '--timeout', '2s', 'api', 'call', 'server.version'])
        version = json.loads(out) if code == 0 else {}
        add('rex_server', code == 0 and isinstance(version.get('api_revision'), int),
            f"{version.get('rex_version', 'unknown')} API {version.get('api_revision', 'unknown')}" if code == 0 else err,
            shlex.join([host['rex'], 'server', 'run', '--listen', 'unix://' + host['socket']]))
    except (OSError, ValueError) as exc:
        add('rex_server', False, str(exc), shlex.join([host['rex'], 'version', '--json']))
    try:
        code, out, err = run_command([str(root / 'install'), '--check'])
        # Build drift has its own check; keep a pin-only mismatch from producing two red lines.
        drift = [line for line in out.splitlines() if line.startswith('drift:') and not line.startswith('drift: teerex build ')]
        add('rexconfig', not drift and (code == 0 or 'drift: teerex build ' in out), '\n'.join(drift) or (err if code else out) or 'configuration matches', install)
    except OSError as exc:
        add('rexconfig', False, str(exc), install)
    try:
        profiles = json.loads((home / '.config/teerex/profiles.json').read_text())
        for harness in ('claude', 'codex'):
            profile = profiles.get('profiles', {}).get(harness, {})
            code, out, err = run_command([host['teerex'], 'agents', 'hook', '--help'])
            add(harness + '_hooks', profile.get('hook_events') is True and code == 0,
                'per-launch hook adapter and profile enabled' if profile.get('hook_events') and code == 0 else 'hook adapter or hook_events profile missing', install)
    except (OSError, ValueError) as exc:
        for harness in ('claude', 'codex'):
            add(harness + '_hooks', False, str(exc), install)
    return checks


def main(argv=None):
    parser = ActionParser(prog='teerex doctor --all')
    parser.add_argument('--all', action='store_true', required=True)
    parser.add_argument('--config', default=str(Path.home() / '.config/teerex/hosts.json'))
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    results = []
    try:
        config = targets.load_config(args.config)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    for name in config['hosts']:
        try:
            host = targets.resolve_host(args.config, name)
            if 'rexconfig' in host:
                targets.absolute(host['rexconfig'], 'rexconfig')
            if host['transport'] == 'local':
                checks = inspect_host(host)
            else:
                script = WORKER_SOURCE + '\nprint(json.dumps(inspect_host(json.loads(sys.argv[1]))))\n'
                command = [*targets.ssh_argv(host), shlex.join(['python3', '-I', '-c', script, json.dumps(host)])]
                code, out, err = run_command(command)
                if code:
                    raise OSError(err or 'remote check failed')
                checks = json.loads(out)
                for check in checks:
                    check['fix'] = shlex.join([*targets.ssh_argv(host), check['fix']])
        except (OSError, ValueError) as exc:
            checks = [dict(check='host_reachable', ok=False, detail=str(exc),
                           fix='ssh ' + shlex.quote(name) + ' true')]
        results.append(dict(host=name, checks=checks))
    packet = dict(schema_version=1, kind='fleet_doctor', ok=all(c['ok'] for h in results for c in h['checks']), hosts=results)
    if args.json:
        print(json.dumps(packet))
    else:
        for host in results:
            for check in host['checks']:
                detail = ' '.join(check['detail'].splitlines())
                print(f"{'✓' if check['ok'] else '✗'} {host['host']} {check['check']}: {detail}" +
                      ('' if check['ok'] else ' | fix: ' + check['fix']))
    for host in results:
        for check in host['checks']:
            if not check['ok']:
                if (sys.stdin.isatty() and sys.stderr.isatty()): print("next: " + check['fix'], file=sys.stderr)
    return 0 if packet['ok'] else 1
