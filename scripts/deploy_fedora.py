#!/usr/bin/env python3
"""Headless Fedora + rootless Podman + Tor v3 onion service for the Streamlit app.

  ./deploy_fedora.py prepare            install podman, enable linger
  ./deploy_fedora.py up [--ephemeral]   build, isolate, start, print .onion URL
  ./deploy_fedora.py url | down | destroy
"""
from __future__ import annotations

import argparse
import getpass
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    root: Path = Path(__file__).resolve().parent.parent
    app_image: str = "localhost/private-streamlit:latest"
    tor_image: str = "localhost/private-tor:latest"
    app_name: str = "streamlit"
    tor_name: str = "tor-hs"
    net_internal: str = "priv-int"   # no internet: app lives here only
    net_egress: str = "priv-out"     # tor-only outbound
    volume: str = "tor-hs-keys"
    max_sessions: str = "25"
    hostname_path: str = "/var/lib/tor/hs/hostname"


class Shell:
    @staticmethod
    def run(*cmd: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, check=check, text=True, capture_output=capture)


class Podman:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def exists(self, kind: str, name: str) -> bool:
        return Shell.run("podman", kind, "exists", name, check=False).returncode == 0

    def ensure_network(self, name: str, internal: bool = False) -> None:
        if not self.exists("network", name):
            args = ["podman", "network", "create"] + (["--internal"] if internal else []) + [name]
            Shell.run(*args, capture=True)

    def build(self, tag: str, file: str) -> None:
        Shell.run("podman", "build", "--no-cache", "-q", "-t", tag, "-f", file, str(self.cfg.root))

    def remove(self, kind: str, name: str) -> None:
        if self.exists(kind, name):
            args = ["podman", kind, "rm", "-f", name] if kind == "container" else ["podman", kind, "rm", name]
            Shell.run(*args, capture=True, check=False)

    def uid_of(self, image: str) -> str:
        return Shell.run("podman", "run", "--rm", "--entrypoint", "id", image, "-u",
                         capture=True).stdout.strip()


class Deployer:
    HARDENING = ("--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                 "--log-driver=none", "--pids-limit=256", "--restart=unless-stopped")

    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        self.pm = Podman(self.cfg)

    def prepare(self) -> None:
        if not shutil.which("podman"):
            Shell.run("sudo", "dnf", "-y", "install", "podman", "crun", "netavark", "aardvark-dns")
        Shell.run("sudo", "loginctl", "enable-linger", getpass.getuser())  # survive logout, headless
        print("Host ready (no ports opened: onion service is outbound-only).")

    def up(self, ephemeral: bool) -> None:
        c = self.cfg
        self.pm.ensure_network(c.net_internal, internal=True)
        self.pm.ensure_network(c.net_egress)
        self.pm.build(c.app_image, "Containerfile")
        self.pm.build(c.tor_image, "Containerfile.tor")
        self.down()

        Shell.run("podman", "run", "-d", "--name", c.app_name, "--network", c.net_internal,
                  *self.HARDENING, "--tmpfs", "/tmp:rw,size=64m,noexec,nosuid",
                  "--memory=512m", "--cpus=1", "-e", f"MAX_SESSIONS={c.max_sessions}", c.app_image)

        if ephemeral:   # keys live in RAM only -> new address each run, nothing on disk
            store = ["--tmpfs", f"/var/lib/tor:rw,mode=0700,uid={self.pm.uid_of(c.tor_image)}"]
        else:           # persistent keys -> stable .onion URL
            store = ["-v", f"{c.volume}:/var/lib/tor:Z"]
        Shell.run("podman", "run", "-d", "--name", c.tor_name,
                  "--network", c.net_internal, "--network", c.net_egress,
                  *self.HARDENING, "--tmpfs", "/tmp:rw,size=32m,noexec,nosuid",
                  "--memory=256m", *store, c.tor_image)
        print("Starting Tor... ", end="", flush=True)
        print(self.url(wait=True))

    def url(self, wait: bool = False, timeout: int = 120) -> str:
        deadline = time.time() + (timeout if wait else 0)
        while True:
            r = Shell.run("podman", "exec", self.cfg.tor_name, "cat", self.cfg.hostname_path,
                          capture=True, check=False)
            if r.returncode == 0 and r.stdout.strip():
                return f"http://{r.stdout.strip()}"
            if time.time() >= deadline:
                return "not ready"
            time.sleep(2)

    def down(self) -> None:
        for n in (self.cfg.tor_name, self.cfg.app_name):
            self.pm.remove("container", n)

    def destroy(self) -> None:
        """Remove every trace: containers, keys, networks, images, build cache."""
        self.down()
        self.pm.remove("volume", self.cfg.volume)
        for n in (self.cfg.net_internal, self.cfg.net_egress):
            self.pm.remove("network", n)
        Shell.run("podman", "rmi", "-f", self.cfg.app_image, self.cfg.tor_image, check=False, capture=True)
        Shell.run("podman", "system", "prune", "-af", "--volumes", check=False, capture=True)
        print("Destroyed.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up")
    up.add_argument("--ephemeral", action="store_true")
    for name in ("prepare", "url", "down", "destroy"):
        sub.add_parser(name)
    a = ap.parse_args()
    d = Deployer()
    {"prepare": d.prepare, "down": d.down, "destroy": d.destroy,
     "url": lambda: print(d.url()), "up": lambda: d.up(a.ephemeral)}[a.cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
