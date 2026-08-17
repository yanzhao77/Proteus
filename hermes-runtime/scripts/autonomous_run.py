#!/usr/bin/env python
"""P6 autonomous production trial CLI.

Runs the full autonomous production trial (happy path + failure scenarios)
against a real PostgreSQL database and writes the evidence bundle under
docs/evidence/p6/ plus the acceptance matrix.

Usage:
    HERMES_P6_DATABASE_URL=postgresql://postgres:hermes@127.0.0.1:55432/hermes_p6_trial     HERMES_P6_TODO_DATABASE_URL=postgresql+psycopg://todo:todo@127.0.0.1:55432/todo_test     PYTHONPATH=src python -m hermes_runtime.trial.harness
"""

from hermes_runtime.trial.harness import main

if __name__ == "__main__":
    raise SystemExit(main())
