"""Bounded, expiring single-process chat memory; no patient text in browser storage.

This local-development store does not survive restarts or synchronize workers.
Replace it with shared persistent sessions/checkpoints for a multi-worker deployment.
"""

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from threading import RLock
from time import time


class ClosedConversation(ValueError):
    pass


class MemoryFull(RuntimeError):
    pass


@dataclass
class Conversation:
    expires_at: float
    turns: deque = field(default_factory=lambda: deque(maxlen=30))
    lock: RLock = field(default_factory=RLock)
    closed: bool = False

    @property
    def messages(self):
        return [message for turn in self.turns for message in turn]


class ChatMemory:
    def __init__(self, capacity=128):
        self.capacity = capacity
        self.entries = {}
        self.lock = RLock()

    @contextmanager
    def turn(self, token: str, expires_at: float):
        key = sha256(token.encode()).hexdigest()
        with self.lock:
            now = time()
            # Expired entries cannot be accessed again; active requests retain
            # their own reference until they finish.
            self.entries = {k: v for k, v in self.entries.items() if v.expires_at > now}
            if expires_at <= now:
                raise ClosedConversation("Please log in again.")
            entry = self.entries.get(key)
            if entry is None:
                if len(self.entries) >= self.capacity:
                    raise MemoryFull("Chat is busy. Please try again shortly.")
                entry = self.entries[key] = Conversation(expires_at)
        # Serialize turns and logout for this signed login, not for arbitrary
        # client-provided thread IDs. Different logins have independent histories.
        with entry.lock:
            if entry.closed or entry.expires_at <= time():
                raise ClosedConversation("Please log in again.")
            yield entry

    def close(self, token: str, expires_at: float):
        with self.turn(token, expires_at) as entry:
            entry.closed = True
            entry.turns.clear()


chat_memory = ChatMemory()
