"""Pure state machine for emergency ping requests.

Kept free of discord.py objects so the voting rules can be unit tested.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Vote(enum.Enum):
    APPROVE = "approve"
    DENY = "deny"


class VoteOutcome(enum.Enum):
    RECORDED = "recorded"
    CHANGED = "changed"
    DUPLICATE = "duplicate"
    SELF_VOTE = "self_vote"
    CLOSED = "closed"


class EmergencyStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass
class EmergencyRequest:
    """Tracks a single pending emergency request and its votes."""

    caller_id: int
    channel_id: int
    guild_id: int
    reason: str
    approval_threshold: int
    deny_threshold: int
    message_id: int | None = None
    message_link: str | None = None
    status: EmergencyStatus = EmergencyStatus.PENDING
    reminders_sent: int = 0
    _votes: dict[int, Vote] = field(default_factory=dict, repr=False)

    @property
    def approvals(self) -> int:
        return sum(1 for vote in self._votes.values() if vote is Vote.APPROVE)

    @property
    def denials(self) -> int:
        return sum(1 for vote in self._votes.values() if vote is Vote.DENY)

    @property
    def is_pending(self) -> bool:
        return self.status is EmergencyStatus.PENDING

    def vote_of(self, user_id: int) -> Vote | None:
        return self._votes.get(user_id)

    def cast(self, user_id: int, vote: Vote) -> VoteOutcome:
        """Record ``vote`` for ``user_id`` and resolve the request if a threshold is met."""
        if not self.is_pending:
            return VoteOutcome.CLOSED
        if user_id == self.caller_id:
            return VoteOutcome.SELF_VOTE

        previous = self._votes.get(user_id)
        if previous is vote:
            return VoteOutcome.DUPLICATE

        self._votes[user_id] = vote
        self._resolve()
        return VoteOutcome.CHANGED if previous is not None else VoteOutcome.RECORDED

    def _resolve(self) -> None:
        if self.approvals >= self.approval_threshold:
            self.status = EmergencyStatus.APPROVED
        elif self.denials >= self.deny_threshold:
            self.status = EmergencyStatus.DENIED

    def cancel(self) -> bool:
        if not self.is_pending:
            return False
        self.status = EmergencyStatus.CANCELLED
        return True

    def time_out(self) -> bool:
        if not self.is_pending:
            return False
        self.status = EmergencyStatus.TIMED_OUT
        return True
