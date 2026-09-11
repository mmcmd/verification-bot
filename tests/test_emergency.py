import pytest

from verification_bot.emergency import EmergencyRequest, EmergencyStatus, Vote, VoteOutcome


@pytest.fixture
def request_():
    return EmergencyRequest(
        caller_id=1,
        channel_id=10,
        guild_id=100,
        reason="Production database is down",
        approval_threshold=3,
        deny_threshold=2,
    )


def test_starts_pending_with_no_votes(request_):
    assert request_.is_pending
    assert request_.approvals == 0
    assert request_.denials == 0


def test_caller_cannot_vote_on_own_request(request_):
    assert request_.cast(1, Vote.APPROVE) is VoteOutcome.SELF_VOTE
    assert request_.approvals == 0


def test_duplicate_vote_is_not_counted_twice(request_):
    assert request_.cast(2, Vote.APPROVE) is VoteOutcome.RECORDED
    assert request_.cast(2, Vote.APPROVE) is VoteOutcome.DUPLICATE
    assert request_.approvals == 1


def test_changing_a_vote_moves_the_tally(request_):
    request_.cast(2, Vote.APPROVE)
    assert request_.cast(2, Vote.DENY) is VoteOutcome.CHANGED
    assert request_.approvals == 0
    assert request_.denials == 1


def test_approval_threshold_resolves_the_request(request_):
    for user_id in (2, 3, 4):
        request_.cast(user_id, Vote.APPROVE)
    assert request_.status is EmergencyStatus.APPROVED
    assert not request_.is_pending


def test_deny_threshold_resolves_the_request(request_):
    request_.cast(2, Vote.DENY)
    request_.cast(3, Vote.DENY)
    assert request_.status is EmergencyStatus.DENIED


def test_votes_after_resolution_are_rejected(request_):
    request_.cast(2, Vote.DENY)
    request_.cast(3, Vote.DENY)
    assert request_.cast(4, Vote.APPROVE) is VoteOutcome.CLOSED
    assert request_.approvals == 0


def test_cancel_only_applies_once(request_):
    assert request_.cancel() is True
    assert request_.cancel() is False
    assert request_.status is EmergencyStatus.CANCELLED


def test_timeout_does_not_override_a_decision(request_):
    for user_id in (2, 3, 4):
        request_.cast(user_id, Vote.APPROVE)
    assert request_.time_out() is False
    assert request_.status is EmergencyStatus.APPROVED


def test_mixed_votes_do_not_resolve_early(request_):
    request_.cast(2, Vote.APPROVE)
    request_.cast(3, Vote.DENY)
    assert request_.is_pending
    assert (request_.approvals, request_.denials) == (1, 1)
