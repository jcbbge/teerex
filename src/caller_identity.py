"""Caller authorization identity: agent metadata, local Rex, then forwarded Rex."""
import os


def caller_identity(environment=None):
    env = os.environ if environment is None else environment
    return dict(session_id=env.get('AGENT_SESSION') or env.get('REX_SESSION') or env.get('LC_REX_SESSION'),
                block_id=env.get('AGENT_PANE') or env.get('REX_BLOCK') or env.get('LC_REX_BLOCK'))
