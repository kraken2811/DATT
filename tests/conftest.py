"""Global pytest safety defaults.

Tests must never call paid/external LLM providers implicitly. Individual tests can
still override these environment variables when validating provider behavior.
"""

import os

os.environ.setdefault("DATT_AGENT_LLM_PROVIDER", "mock")
os.environ.setdefault("DATT_AGENT_LLM_MODEL", "mock")
