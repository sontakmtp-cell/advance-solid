"""Test configuration."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TEST_TMP = ROOT / ".pytest-tmp"
TEST_TMP.mkdir(exist_ok=True)

os.environ.setdefault("TEMP", str(TEST_TMP))
os.environ.setdefault("TMP", str(TEST_TMP))
os.environ.setdefault("TMPDIR", str(TEST_TMP))
os.environ.setdefault("SOLIDWORKS_MCP_WORKSPACE_ROOTS", str(ROOT))
os.environ.setdefault("SOLIDWORKS_MCP_BACKEND", "headless")


@pytest.fixture
def tmp_path(request: pytest.FixtureRequest) -> Path:
    safe_name = request.node.name.replace("[", "_").replace("]", "_").replace("\\", "_")
    path = TEST_TMP / f"{safe_name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path
