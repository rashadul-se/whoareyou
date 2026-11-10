"""Privacy-first Streamlit app: no analytics, no persistence, no IP handling."""
from __future__ import annotations

import os
import secrets
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True, slots=True)
class Settings:
    max_sessions: int = 25      # hard cap; always >= 5 concurrent users
    ttl_seconds: int = 90       # idle session expiry
    heartbeat_seconds: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            max_sessions=max(5, int(os.getenv("MAX_SESSIONS", "25"))),
            ttl_seconds=max(30, int(os.getenv("SESSION_TTL", "90"))),
        )


class SessionRegistry:
    """Thread-safe, in-memory admission control. Stores random IDs only."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def _prune(self, now: float) -> None:
        for sid in [k for k, t in self._seen.items() if now - t > self._s.ttl_seconds]:
            del self._seen[sid]

    def touch(self, sid: str) -> bool:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if sid in self._seen or len(self._seen) < self._s.max_sessions:
                self._seen[sid] = now
                return True
            return False

    def active(self) -> int:
        with self._lock:
            self._prune(time.monotonic())
            return len(self._seen)


@st.cache_resource(show_spinner=False)
def get_registry() -> SessionRegistry:
    return SessionRegistry(Settings.from_env())


class Page(ABC):
    title: str

    @abstractmethod
    def render(self) -> None: ...


class ScratchpadPage(Page):
    title = "Scratchpad"
    _KEY = "pad"

    def render(self) -> None:
        st.text_area("Private notes (RAM only, wiped when you close the tab)",
                     key=self._KEY, height=300)
        c1, c2 = st.columns(2)
        c1.download_button("Save locally", st.session_state.get(self._KEY, ""),
                           file_name="notes.txt", use_container_width=True)
        if c2.button("Wipe now", use_container_width=True):
            st.session_state[self._KEY] = ""
            st.rerun()


class PrivacyPage(Page):
    title = "Privacy"

    def render(self) -> None:
        st.markdown(
            "- No cookies, analytics, or third-party requests\n"
            "- Nothing is written to disk; state lives in RAM per session\n"
            "- Session IDs are random and unrelated to your IP or device\n"
            "- Capacity guard keeps the service stable for concurrent users"
        )


class App:
    def __init__(self, pages: list[Page]) -> None:
        self._pages = pages
        self._settings = Settings.from_env()
        self._registry = get_registry()

    def _session_id(self) -> str:
        return st.session_state.setdefault("sid", secrets.token_hex(8))

    def run(self) -> None:
        st.set_page_config(page_title="Private Space", page_icon="🔒", layout="centered")
        sid = self._session_id()
        if not self._registry.touch(sid):
            st.warning("Server is at capacity. Please retry in a minute.")
            st.stop()

        @st.fragment(run_every=self._settings.heartbeat_seconds)
        def heartbeat() -> None:
            self._registry.touch(sid)

        heartbeat()
        st.title("🔒 Private Space")
        for tab, page in zip(st.tabs([p.title for p in self._pages]), self._pages):
            with tab:
                page.render()


if __name__ == "__main__" or True:  # Streamlit executes the module as a script
    App([ScratchpadPage(), PrivacyPage()]).run()
