"""Command guides in leaf and explicitly allowlisted, read-only try-it examples."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import termios
import tty

# The launcher supplies the binary's own README bundle, never an installed checkout.
SELF = sys.argv[1]
GUIDES = json.loads(sys.argv[2])
ALIASES = {'compare': 'observe', 'watch': 'observe', 'run-visible': 'run',
           'ask': 'boards', 'seat': 'boards', 'inbox': 'boards',
           'snapshot': 'recovery', 'restore': 'recovery', 'update': 'recovery',
           'maneuver-check': 'maneuvers', 'feed': 'boardfeed', 'targets': 'targets',
           'fleet': 'fleet', 'cartridges': 'cartridges'}
COMMANDS = sorted((set(GUIDES) - {'boardfeed', 'maneuvers'}) | set(ALIASES))
# Only these fixed argv forms receive try IDs. README snippets are never executed.
EXAMPLES = {name + '-help': [name, '--help'] for name in COMMANDS}
EXAMPLES['version'] = ['--version']
EXAMPLES['observe-self'] = ['observe', '--session', '{session}', '--block', '{block}', '--tail']
EXAMPLES['surfaces-self'] = ['surfaces', 'inspect', '--session', '{session}', '--pane', '{block}']


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def page(command):
    if command is None:
        return '# teerex docs\n\nOpen a guide with `teerex docs COMMAND`.\n\n' + '\n'.join(
            '- `teerex docs ' + name + '`' for name in COMMANDS) + (
            '\n\n## Try it\n\n`teerex docs try version` — read-only; prints this build’s version.\n'
            'Each command page has a read-only help example. Only listed try IDs run.\n')
    if command not in COMMANDS:
        raise ValueError('unknown command: ' + command)
    guide = run([SELF, "docs", "_readme", ALIASES.get(command, command)], capture_output=True, text=True).stdout
    help_text = run([SELF, command, '--help'], capture_output=True, text=True).stdout
    examples = re.findall(r'```(?:sh|bash|shell)\n(.*?)```', guide, re.S)
    body = ('# teerex ' + command + '\n\n## Try it\n\n'
            '`teerex docs try ' + command + '-help`\n\n'
            'Safe: read-only. Runs `teerex ' + command + ' --help` in a temporary pane and directory. '
            'Press any key to close it. No input is sent to existing panes.\n\n'
            '## README examples\n\n'
            'These examples may require real targets or change live work. They have no try ID.\n\n')
    if command in ('observe', 'surfaces'):
        body += '`teerex docs try ' + command + '-self` — safe, read-only inspection of the example pane itself.\n\n'
    for i, example in enumerate(examples, 1):
        body += '### ' + command + '-example-' + str(i) + '\n\n```sh\n' + example + '```\n\n'
    if not examples:
        body += 'No shell examples in this item’s README.\n\n'
    return body + '## Command help\n\n````text\n' + help_text + '\n````\n\n## Item README\n\n' + guide


def context(o):
    session = o.session or os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION')
    block = o.block or os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK')
    if not session or not block:
        raise ValueError('invoke from an attached Rex pane or pass --session and --block')
    return session, block


def surface(o, label, argv):
    session, block = context(o)
    args = [SELF, 'surfaces', 'open', '--socket', o.socket, '--session', session,
            '--anchor', block, '--layout', 'float', '--bounds', '[0.08,0.08,0.84,0.84]',
            '--label', label, '--', *argv]
    opened = json.loads(run(args, capture_output=True, text=True).stdout)
    pane = opened['created']['block_id']
    try:
        focused = json.loads(run([SELF, 'surfaces', 'focus', '--socket', o.socket,
                                 '--session', session, '--pane', pane], capture_output=True, text=True).stdout)
    except BaseException:
        print(json.dumps(dict(open=opened, focus='unknown')), flush=True)
        raise
    print(json.dumps(dict(open=opened, focus=focused)), flush=True)


def try_runner(example, socket=None):
    # No arbitrary shell, source snippet, host, target, environment or file arguments.
    # All allowlisted commands only print help/version or inspect this pane; none opens child panes.
    with tempfile.TemporaryDirectory(prefix='teerex-docs-try-') as directory:
        argv = [value.format(session=os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION', ''),
                             block=os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK', ''))
                for value in EXAMPLES[example]]
        if example.endswith('-self'):
            argv += ['--socket', socket]
        result = subprocess.run([SELF, *argv], cwd=directory)
        print('\nExit:', result.returncode, '\nPress any key to close this sandbox.', flush=True)
        with open('/dev/tty', 'rb', buffering=0) as terminal:
            previous = termios.tcgetattr(terminal)
            try:
                tty.setraw(terminal)
                terminal.read(1)
            finally:
                termios.tcsetattr(terminal, termios.TCSADRAIN, previous)
        return result.returncode


def main():
    p = argparse.ArgumentParser(prog='teerex docs', description=__doc__)
    p.add_argument('command', nargs='?', help='command guide, or try')
    p.add_argument('id', nargs='?', help='allowlisted read-only example ID')
    p.add_argument('--file', help='new palette fragment path (docs palette)')
    p.add_argument('--rex', help='absolute Rex executable for generated action')
    p.add_argument('--teerex', default=SELF, help='stable teerex path for generated action')
    p.add_argument('--session')
    p.add_argument('--block')
    p.add_argument('--socket', default=os.environ.get('REX_SERVER', '').removeprefix('unix://') or
                   (str(Path.home() / 'Library/Application Support/rex/server.sock') if sys.platform == 'darwin'
                    else '/run/user/' + str(os.getuid()) + '/rex/server.sock'))
    o = p.parse_args(sys.argv[3:])
    if o.command == 'palette':
        for value in (o.file, o.rex, o.teerex, o.socket):
            if not value or not os.path.isabs(value) or any(ord(c) < 32 for c in value):
                raise ValueError('absolute palette, Rex, teerex and socket paths required')
        argv = [o.teerex, '--rex', o.rex, 'docs', '--socket', o.socket]
        # JSON is embedded as a Lua quoted string using decimal control escapes.
        encoded = json.dumps(argv)
        quoted = '"' + ''.join('\\' + c if c in '\\"' else '\\%03d' % ord(c) if ord(c) < 32 else c for c in encoded) + '"'
        body = """-- teerex-surface-action:teerex_docs
rex.action{name='teerex_docs',title='teerex docs',category='teerex',run=function(ctx)
if not ctx.session_id or not ctx.block_id then error('invoke from an attached pane',0) end
local argv=rex.json.decode(ARGV)
for _,v in ipairs({'--session',ctx.session_id,'--block',ctx.block_id}) do argv[#argv+1]=v end
local r=rex.exec(argv,{timeout=20})
if type(r)~='table' or not r.ok then error('docs opening uncertain; inspect before retry',0) end
return rex.json.decode(r.stdout)
end}
""".replace('ARGV', quoted)
        fd = os.open(o.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(body)
        print(json.dumps(dict(outcome='generated', file=o.file, installed=False)))
        return 0
    if o.command in ('try', '_try'):
        if o.id not in EXAMPLES:
            raise ValueError('unknown or unsafe example ID; open its command guide for try IDs')
        if o.command == '_try':
            result = try_runner(o.id, o.socket)
            session, block = context(o)
            run([SELF, 'surfaces', 'close', '--socket', o.socket, '--session', session, '--pane', block])
            return result
        surface(o, 'Try teerex ' + o.id, [SELF, 'docs', '_try', o.id, '--socket', o.socket])
        return 0
    if o.id:
        p.error('unexpected example ID; use docs try ID')
    text = page(o.command)
    leaf = shutil.which('leaf') or str(Path.home() / '.cargo/bin/leaf')
    # Pages follow the live binary and are kept while leaf has the path open.
    # A private per-invocation file avoids overwriting another reader’s guide.
    root = Path.home() / '.local/state/teerex/docs'
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix=(o.command or 'index') + '-', suffix='.md', dir=root)
    with os.fdopen(fd, 'w') as output:
        output.write(text)
    viewer = "import os,subprocess,sys\ntry:\n subprocess.run(sys.argv[1:],check=True)\nfinally:\n os.unlink(sys.argv[-1])"
    try:
        surface(o, 'teerex docs ' + (o.command or 'index'), ['python3', '-I', '-c', viewer, leaf, 'open', path])
    except BaseException:
        # An uncertain open may have a reader: retain its private path for inspection.
        print('Guide retained at ' + path, file=sys.stderr)
        raise
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print('teerex docs: ' + str(exc), file=sys.stderr)
        sys.exit(1)
