#!/usr/bin/env python3
"""Execute an operator command with dotenv values, without shell evaluation."""
import os
import sys
from dotenv import dotenv_values

if len(sys.argv) < 3:
    raise SystemExit("usage: env-run.py ENV_FILE COMMAND [ARG ...]")
values = dotenv_values(sys.argv[1], interpolate=False)
env = dict(os.environ)
env.update({key: value for key, value in values.items() if value is not None})
os.execvpe(sys.argv[2], sys.argv[2:], env)
