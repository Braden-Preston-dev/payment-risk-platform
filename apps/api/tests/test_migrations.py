import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for destructive migration round-trip testing",
)
def test_migrations_upgrade_downgrade_upgrade():
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"], "PYTHONPATH": str(root)}
    for target in ("head", "base", "head"):
        command = [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini")]
        command += ["downgrade" if target == "base" else "upgrade", target]
        subprocess.run(command, cwd=root, env=env, check=True)
