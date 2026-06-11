"""
Boundary control and safety constraints for the pre-rehearsal system.

Enforces:
  1. Chapter cap (max 30 per version)
  2. NPC count cap
  3. Per-call token limit
  4. Total token budget
  5. Ctrl+C graceful exit
  6. Repeat-action detection
  7. Version timeout
"""

import asyncio
import time
import signal
from dataclasses import dataclass, field
from typing import Optional

from .utils import logger, detect_repeated_action


# ---------------------------------------------------------------------------
# Token budget tracker (shared across all versions)
# ---------------------------------------------------------------------------

class TokenBudget:
    """Thread-safe token budget tracker shared across async coroutines."""

    def __init__(self, total_budget: Optional[int] = None):
        self.total_budget = total_budget  # None = unlimited
        self.used = 0
        self._lock = asyncio.Lock()
        self.exceeded = False

    async def consume(self, tokens: int) -> bool:
        """
        Try to consume tokens. Returns True if allowed, False if budget exceeded.
        """
        if self.total_budget is None:
            async with self._lock:
                self.used += tokens
            return True

        async with self._lock:
            if self.used + tokens > self.total_budget:
                self.exceeded = True
                return False
            self.used += tokens
            return True

    @property
    def remaining(self) -> Optional[int]:
        if self.total_budget is None:
            return None
        return max(0, self.total_budget - self.used)

    async def get_used(self) -> int:
        async with self._lock:
            return self.used


# ---------------------------------------------------------------------------
# Repeat-action detector
# ---------------------------------------------------------------------------

class RepeatDetector:
    """Detects if the same agent is repeating nearly identical actions."""

    def __init__(self, threshold: float = 0.9, window: int = 3):
        self.threshold = threshold
        self.window = window

    def check_protagonist(self, actions: list) -> bool:
        """Check the last `window` protagonist actions for repetition."""
        if len(actions) < self.window:
            return False

        # Compare the 'content' + 'action' fields combined
        def get_text(a):
            return f"{a.action}: {a.content}"

        return detect_repeated_action(actions, get_text, self.threshold, self.window)

    def check_npc(self, npc_id: str, actions: list) -> bool:
        """Check the last actions of a specific NPC for repetition."""
        npc_actions = [a for a in actions if hasattr(a, 'agent_name') and a.agent_name == npc_id]
        if len(npc_actions) < self.window:
            return False

        def get_text(a):
            return f"{a.action}: {a.content}"

        return detect_repeated_action(npc_actions, get_text, self.threshold, self.window)


# ---------------------------------------------------------------------------
# Chapter and NPC constraints
# ---------------------------------------------------------------------------

@dataclass
class VersionConstraints:
    """Per-version constraint checker."""
    max_chapters: int = 30
    max_npcs: int = 15
    max_tokens_per_call: int = 2000
    repeat_threshold: float = 0.9

    def can_add_chapter(self, current_chapter: int) -> bool:
        return current_chapter < self.max_chapters

    def can_add_npc(self, current_npc_count: int) -> bool:
        return current_npc_count < self.max_npcs

    def enforce_token_per_call(self, requested: int) -> int:
        return min(requested, self.max_tokens_per_call)


# ---------------------------------------------------------------------------
# Graceful shutdown handler
# ---------------------------------------------------------------------------

class ShutdownHandler:
    """Captures SIGINT (Ctrl+C) and sets a shutdown flag for graceful exit."""

    def __init__(self):
        self.shutdown_requested = False
        self._original_handler = None

    def _on_signal(self, signum, frame):
        logger.warning("\n⚠ Ctrl+C 收到，正在保存当前进度并退出...")
        self.shutdown_requested = True
        # Restore original handler so a second Ctrl+C hard-kills
        if self._original_handler:
            signal.signal(signal.SIGINT, self._original_handler)

    def install(self):
        """Install the signal handler."""
        self._original_handler = signal.signal(signal.SIGINT, self._on_signal)
        return self

    def uninstall(self):
        """Restore the original signal handler."""
        if self._original_handler:
            signal.signal(signal.SIGINT, self._original_handler)


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------

class TimeoutTracker:
    """Tracks elapsed time for a single version's execution."""

    def __init__(self, timeout_seconds: float):
        self.timeout = timeout_seconds
        self.start_time: Optional[float] = None

    def start(self):
        self.start_time = time.time()

    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return time.time() - self.start_time

    def is_expired(self) -> bool:
        return self.elapsed() >= self.timeout

    def remaining(self) -> float:
        return max(0.0, self.timeout - self.elapsed())
