"""Caller authorization identity: agent metadata, local Rex, then forwarded Rex."""
import os


def caller_identity(environment=None):
    env = os.environ if environment is None else environment
    return dict(session_id=env.get('AGENT_SESSION') or env.get('REX_SESSION') or env.get('LC_REX_SESSION'),
                block_id=env.get('AGENT_PANE') or env.get('REX_BLOCK') or env.get('LC_REX_BLOCK'))


def managed_agent(environment=None):
    env = os.environ if environment is None else environment
    markers = ('AGENT_LAUNCH_ID', 'AGENT_NAME', 'AGENT_SESSION', 'AGENT_PANE',
               'AGENT_CHANNEL', 'AGENT_STARTER', 'AGENT_REPORT_TO')
    return any(env.get(prefix + key) for prefix in ('', 'LC_') for key in markers)


def human_identity(environment=None):
    """OS identity, never a claimed USER/HOSTNAME or an invented pane address."""
    import pwd
    import socket
    env = os.environ if environment is None else environment
    identity = dict(host=socket.gethostname(), user=pwd.getpwuid(os.getuid()).pw_name)
    client = (env.get('SSH_CONNECTION') or env.get('SSH_CLIENT') or '').split()
    if client:
        identity['ssh_client_host'] = client[0]
    return identity
