"""Read harness accounting; no transcript contents leave this module."""
import datetime
import json
import math
import os
from pathlib import Path
import re
import stat


def cost_settings(profile):
    value = profile.get('cost', {})
    require(isinstance(value, dict), 'invalid_cost_profile')
    result = dict(turn_seconds=value.get('turn_seconds', 7200), turn_tokens=value.get('turn_tokens', 1000000),
                  rates=value.get('rates', {}), rivet_item=value.get('rivet_item'))
    for field in ('turn_seconds', 'turn_tokens'):
        require(type(result[field]) in (int, float) and math.isfinite(result[field]) and result[field] > 0,
                'invalid_cost_' + field)
    require(isinstance(result['rates'], dict), 'invalid_cost_rates')
    for model, rates in result['rates'].items():
        require(isinstance(model, str) and isinstance(rates, dict) and
                set(rates) == {'input', 'output', 'cache_read', 'cache_write'} and
                all(type(v) in (float, int) and math.isfinite(v) and v >= 0 for v in rates.values()), 'invalid_cost_rates')
    require(result['rivet_item'] is None or isinstance(result['rivet_item'], str) and result['rivet_item'] and
            not result['rivet_item'].startswith('-'), 'invalid_cost_rivet_item')
    return result


def cost_lines(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, encoding='utf-8') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('transcript_not_owned_regular_file')
        for line in stream:
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    yield value
            except ValueError:
                continue  # A writer may not have finished its final line.


def cost_time(value):
    try:
        if isinstance(value, (int, float)):
            return int(value)
        return int(datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
    except (TypeError, ValueError, OverflowError, AttributeError):
        return 0


def cost_paths(harness, home=None):
    home = Path(home or Path.home())
    roots = {'claude': (home / '.claude/projects', '*.jsonl'),
             'codex': (home / '.codex/sessions', '*.jsonl'),
             'pi': (home / '.pi/agent/sessions', '*.jsonl')}
    if harness not in roots:
        return []
    root, pattern = roots[harness]
    return root.rglob(pattern)


def cost_user(record):
    if record.get('type') == 'response_item':
        msg = record.get('payload', {})
    else:
        msg = record.get('message', {})
    if isinstance(msg, dict) and msg.get('role') == 'user':
        return json.dumps(msg.get('content', ''), ensure_ascii=False)
    if record.get('type') == 'user':
        return json.dumps(msg.get('content', ''), ensure_ascii=False)
    return ''


def cost_matches(states):
    """Exact protocol launch IDs, never cwd/time proximity. Scan each file once."""
    found = {s['launch_id']: [] for s in states}
    by_harness = {}
    for state in states:
        by_harness.setdefault(state.get('harness'), {})[state['launch_id']] = state
    errors = []
    for harness, launches in by_harness.items():
        for path in cost_paths(harness):
            try:
                # Files older than every launch cannot contain its protocol.
                if path.stat().st_mtime * 1000 < min(s['created_at'] for s in launches.values()):
                    continue
                for record in cost_lines(path):
                    user = cost_user(record)
                    if 'Messaging protocol (not a task brief):' in user:
                        ids = set(re.findall(r'--launch-id ([0-9a-f]{32})', user))
                        for launch_id in ids & launches.keys():
                            found[launch_id].append(str(path))
                        break
                    # Protocol is the first user prompt of a managed launch.
                    if record.get('type') == 'token_usage_record' or record.get('message', {}).get('usage'):
                        break
            except (OSError, ValueError) as exc:
                errors.append(dict(path=str(path), error=str(exc)))
    return found, errors


def cost_usage(path, harness, turn_at=0, rates=None):
    total = dict(input=0, output=0, cache_read=0, cache_write=0)
    turn_tokens, dollars, priced, usage_seen = 0, 0.0, True, False
    messages = {}
    cumulative = {}
    model = None
    last_at = 0
    for record in cost_lines(path):
        at = cost_time(record.get('timestamp'))
        last_at = max(last_at, at)
        payload = record.get('payload', {})
        if record.get('type') == 'turn_context':
            model = payload.get('model', model)
        if harness == 'codex':
            usage = None
            if record.get('type') == 'token_usage_record':
                usage = payload.get('thread_token_usage')
            elif payload.get('type') == 'token_count':
                usage = (payload.get('info') or {}).get('total_token_usage')
            if not usage:
                continue
            current = dict(input=usage.get('input_tokens', 0), output=usage.get('output_tokens', 0),
                           cache_read=usage.get('cached_input_tokens', 0), cache_write=usage.get('cache_write_input_tokens', 0))
            # Both event formats describe the same cumulative usage.
            delta = {k: max(0, v - cumulative.get(k, 0)) for k, v in current.items()}
            cumulative = current
            delta['input'] = max(0, delta['input'] - delta['cache_read'] - delta['cache_write'])
            key = None
            recorded = None
        else:
            msg = record.get('message', {})
            if not isinstance(msg, dict) or msg.get('role', record.get('type')) != 'assistant':
                continue
            usage = msg.get('usage')
            if not isinstance(usage, dict):
                continue
            model = msg.get('model', model)
            if harness == 'claude':
                delta = dict(input=usage.get('input_tokens', 0), output=usage.get('output_tokens', 0),
                             cache_read=usage.get('cache_read_input_tokens', 0), cache_write=usage.get('cache_creation_input_tokens', 0))
                # Streaming assistant blocks repeat the message's usage; keep its latest snapshot.
                key = msg.get('id') or record.get('uuid')
                recorded = usage.get('costUSD')
            else:
                delta = dict(input=usage.get('input', 0), output=usage.get('output', 0),
                             cache_read=usage.get('cacheRead', 0), cache_write=usage.get('cacheWrite', 0))
                key = record.get('id')
                recorded = (usage.get('cost') or {}).get('total')
        usage_seen = True
        amount = recorded
        source = 'recorded'
        if amount is None and model in (rates or {}):
            amount = sum(delta[k] * rates[model][k] / 1000000 for k in delta)
            source = 'estimate_profile_rates'
        entry = (delta, at, amount, source)
        if key:
            messages[key] = entry
        else:
            messages[len(messages)] = entry
    sources = set()
    for delta, at, amount, source in messages.values():
        for k in total:
            total[k] += delta[k]
        if at >= turn_at:
            turn_tokens += sum(delta.values())
        if amount is None:
            priced = False
        else:
            dollars += amount
            sources.add(source)
    return dict(tokens_in=total['input'] + total['cache_read'] + total['cache_write'], tokens_out=total['output'],
                cache_read_tokens=total['cache_read'], cache_write_tokens=total['cache_write'],
                turn_tokens=turn_tokens, dollars=dollars if priced and usage_seen else None,
                dollar_source='+'.join(sorted(sources)) if priced and usage_seen else 'unknown_not_recorded',
                usage_seen=usage_seen, last_at=last_at)


def cost_row(state, paths):
    start = state.get('immediate_child_started_at') or state['created_at']
    end = state.get('immediate_child_ended_at') or now()
    turn_at = state.get('turn_started_at', start)
    hook = state.get('last_hook') or {}
    active = state.get('immediate_child_term') is None and hook.get('kind') not in ('Stop', 'StopFailure')
    settings = state.get('cost') or cost_settings({})
    row = dict(name=state['name'], launch_id=state['launch_id'], harness=state.get('harness'), target=state.get('target'),
               wall_seconds=max(0, end - start) / 1000, current_turn_seconds=max(0, end - turn_at) / 1000 if active else 0,
               turn_active=active, transcript=paths[0] if len(paths) == 1 else None,
               tokens_in=None, tokens_out=None, turn_tokens=None, dollars=None, dollar_source='unknown_not_recorded',
               match='exact_protocol_launch_id' if len(paths) == 1 else ('ambiguous' if paths else 'not_found'),
               threshold=settings, flag=state.get('cost_flag'))
    if len(paths) == 1:
        try:
            row.update(cost_usage(paths[0], state.get('harness'), turn_at, settings['rates']))
        except (OSError, ValueError) as exc:
            row['usage_error'] = str(exc)
    return row


def cost_flag(root, state, row):
    settings = row['threshold']
    exceeded = row['current_turn_seconds'] >= settings['turn_seconds'] or (row.get('turn_tokens') or 0) >= settings['turn_tokens']
    if not row['turn_active'] or not exceeded or not state.get('starter') or state.get('cost_flag'):
        return
    claimed = []
    def claim(s):
        if not s.get('cost_flag'):
            s['cost_flag'] = dict(at=now(), outcome='attempted_not_retried', turn_seconds=row['current_turn_seconds'], turn_tokens=row.get('turn_tokens'))
            claimed.append(True)
    update(root, state['launch_id'], claim)
    if not claimed:
        return
    body = f"COST {state['name']}: current turn {row['current_turn_seconds'] / 3600:.2f} hours, {row.get('turn_tokens')} tokens. Threshold exceeded; agent continues."
    code, packet = send(root, state, state['starter'], body, 'cost-threshold')
    update(root, state['launch_id'], lambda s: s['cost_flag'].update(outcome='acknowledged' if transport_ack(code, packet) else 'uncertain_not_retried'))


def cost(o):
    root = Path(absolute(o.registry))
    require(root.is_dir() and not root.is_symlink(), 'invalid_registry_directory')
    states = []
    paths = list(root.glob('agents-*.json')) + list(root.glob('archive/*/retired.json'))
    since = since_timestamp(o.since)
    for path in paths:
        state = json.loads(read_file(str(path), limit=None, private=True))
        if state.get('created_at', 0) >= since:
            states.append(state)
    matched, errors = cost_matches(states)
    rows = [cost_row(s, matched[s['launch_id']]) for s in states]
    # This command is observational; existing in-pane supervisors send threshold notices.
    items = set(o.rivet_item or []) | {s.get('cost', {}).get('rivet_item') for s in states}
    rivet = [cost_rivet(item) for item in sorted(i for i in items if i)]
    result = dict(schema_version=1, kind='agents_cost', agents=rows, rivet_items=rivet, read_errors=errors,
                  snapshot='transcript_usage_not_billing_invoice')
    if o.json:
        return 0, result
    print('NAME  TOKENS IN / OUT  DOLLARS  WALL  TURN')
    for row in rows:
        dollars = 'unknown' if row['dollars'] is None else '$%.4f (%s)' % (row['dollars'], row['dollar_source'])
        safe_name = ''.join(c for c in row['name'] if c.isprintable())
        print(f"{safe_name}  {row['tokens_in']} / {row['tokens_out']}  {dollars}  {row['wall_seconds'] / 3600:.2f}h  {row['current_turn_seconds'] / 3600:.2f}h")
    for item in rivet:
        print('Rivet %s  %s' % (item['item'], item.get('dollars', 'unknown')))
    return 0, None


def cost_rivet(item):
    require(isinstance(item, str) and item and not item.startswith('-'), 'invalid_cost_rivet_item')
    try:
        result = subprocess.run(['rv', 'show', item], capture_output=True, text=True, timeout=15)
        if result.returncode:
            return dict(item=item, dollars=None, source='rv show', error='rv_show_failed')
        # rv show renders each call cost to three decimal places; retain that precision.
        clean = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        amounts = re.findall(r' · \$(\d+(?:\.\d+)?)', clean)
        return dict(item=item, dollars=round(sum(float(v) for v in amounts), 3) if amounts else None,
                    source='rv show displayed call costs (rounded)', cost_entries=len(amounts))
    except (OSError, subprocess.SubprocessError):
        return dict(item=item, dollars=None, source='rv show', error='rv_show_unavailable')
