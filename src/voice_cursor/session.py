from __future__ import annotations

from enum import Enum


class Phase(Enum):
    LISTENING = "listening"
    RUNNING = "running"
    SPEAKING = "speaking"
    STOPPING = "stopping"


class Session:
    def __init__(self) -> None:
        self.phase = Phase.LISTENING
        self.last_spoken = ""

    @property
    def run_active(self) -> bool:
        return self.phase is Phase.RUNNING

    @property
    def speaking(self) -> bool:
        return self.phase is Phase.SPEAKING

    @property
    def is_open(self) -> bool:
        return self.phase is not Phase.STOPPING

    def begin_run(self) -> None:
        if self.phase is Phase.STOPPING:
            return
        self.phase = Phase.RUNNING

    def begin_speak(self) -> None:
        if self.phase is Phase.STOPPING:
            return
        self.phase = Phase.SPEAKING

    def end_turn(self) -> None:
        if self.phase is Phase.STOPPING:
            return
        self.phase = Phase.LISTENING

    def stop(self) -> None:
        self.phase = Phase.STOPPING
