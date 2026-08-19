"""Test harness for bmox scripts.

Each test gets its own CLAUDE_PROJECT_DIR so state.py and knowledge.py write
into an isolated .bmox/. This works only because their paths are resolved
lazily per call — module-level path constants would bind to the first test's
temp directory and leak into every later one.
"""
import json
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


class Bmox:
    def __init__(self, root, monkeypatch):
        self.root = root
        self._monkeypatch = monkeypatch

    def run(self, *argv):
        """Invoke the CLI exactly as a skill would."""
        import state
        self._monkeypatch.setattr(sys, "argv", ["state.py", *argv])
        state.main()

    def state(self):
        with open(os.path.join(self.root, ".bmox", "state.json")) as f:
            return json.load(f)

    def profile(self):
        with open(os.path.join(self.root, ".bmox", "profile.json")) as f:
            return json.load(f)

    def step(self, n, project="kafka"):
        return self.state()["projects"][project]["steps"][f"step_{n}"]

    def write(self, relpath, content):
        """Create a file under the learner repo root, making parents."""
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return relpath


@pytest.fixture
def bmox(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return Bmox(str(tmp_path), monkeypatch)
