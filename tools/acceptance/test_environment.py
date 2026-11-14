"""Environment copies for tests that simulate a Rex caller."""
import os


def isolated_environment():
    """Discard the runner's identity before a test supplies its own caller."""
    environment = dict(os.environ)
    for key in ('AGENT_SESSION', 'AGENT_PANE', 'LC_REX_SESSION', 'LC_REX_BLOCK'):
        environment.pop(key, None)
    return environment
