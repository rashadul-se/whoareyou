#!/usr/bin/env python3
"""Push to GitHub and (optionally) trigger a Render deploy.

First time: create the repo on GitHub, then in Render choose
  New > Blueprint > select repo (render.yaml is picked up automatically).
After that every `git push` auto-deploys; this script just wraps it.

  export RENDER_DEPLOY_HOOK='https://api.render.com/deploy/srv-xxx?key=yyy'  # optional
  ./render_deploy.py -m "update"
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = ("Containerfile", "render.yaml", "requirements.txt", "app/main.py", ".streamlit/config.toml")


class GitPublisher:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(("git", *args), cwd=self.root, text=True, check=check)

    def publish(self, message: str) -> None:
        if not (self.root / ".git").exists():
            self._git("init", "-b", "main")
        self._git("add", "-A")
        self._git("commit", "-m", message, check=False)   # no-op if nothing changed
        self._git("push", "-u", "origin", "main")


class RenderClient:
    def __init__(self, hook: str | None) -> None:
        self.hook = hook

    def trigger(self) -> None:
        if not self.hook:
            print("No RENDER_DEPLOY_HOOK set; relying on autoDeploy from the push.")
            return
        with urllib.request.urlopen(urllib.request.Request(self.hook, method="POST"), timeout=15) as r:
            print(f"Render deploy triggered (HTTP {r.status}).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-m", "--message", default="deploy")
    msg = ap.parse_args().message
    missing = [f for f in REQUIRED if not (ROOT / f).exists()]
    if missing:
        sys.exit(f"Missing files: {missing}")
    GitPublisher(ROOT).publish(msg)
    RenderClient(os.getenv("RENDER_DEPLOY_HOOK")).trigger()
    return 0


if __name__ == "__main__":
    sys.exit(main())
