"""Inbound observation validation for D9.

The extension may send:
- An observation with `seq`: track via SequenceTracker, drop duplicates.
- An observation without `seq`: legacy mode, accept (and warn once).
- An observation_error / evaluate_result / human_reply: control frames,
  no seq.
- A ping: control frame, no seq.

This module is the single seam against which the WS handler validates
incoming messages. The tracker is created per session and held by the
session registry so reconnects reuse the same tracker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .sequence_tracker import SequenceTracker

log = logging.getLogger("brotto.obs_validator")


@dataclass
class ObservationDecision:
    """Outcome of validating an inbound message.

    - `accept`: pass the message through to the agent loop.
    - `drop_duplicate`: sender resent an old observation; ignore.
    - `drop_invalid`: malformed or unknown type; close the WS.
    """

    accept: bool
    reason: str = ""
    log_level: str = "debug"


def validate_observation(
    incoming: dict,
    tracker: SequenceTracker,
    *,
    is_legacy_warned: bool = False,
) -> ObservationDecision:
    """Decide whether to accept an inbound message.

    Args:
        incoming: parsed JSON dict from the extension.
        tracker: per-session SequenceTracker.
        is_legacy_warned: has this session already logged a no-seq warning?

    Returns:
        ObservationDecision — accept/drop and rationale.
    """
    msg_type = incoming.get("type")

    if msg_type != "observation":
        # Control frames (observation_error, evaluate_result, human_reply,
        # ping) do not carry a seq. Accept them.
        return ObservationDecision(accept=True, reason="control_frame")

    seq = incoming.get("seq")
    if seq is None:
        # Legacy extension. Accept and warn once per session.
        if not is_legacy_warned:
            log.warning(
                "inbound observation missing seq — legacy extension. "
                "Continuing without dedup."
            )
        return ObservationDecision(accept=True, reason="legacy_no_seq")

    if not isinstance(seq, int) or seq < 0:
        log.warning("inbound observation has invalid seq=%r", seq)
        return ObservationDecision(accept=False, reason="invalid_seq", log_level="warning")

    status = tracker.observe(seq)
    if status == "duplicate":
        log.debug("dropping duplicate observation seq=%s", seq)
        return ObservationDecision(accept=False, reason="duplicate", log_level="debug")

    if status == "gap":
        log.warning(
            "observation gap: last_seq=%s got seq=%s — accepting",
            tracker.last_seq - 1, seq,
        )
        return ObservationDecision(accept=True, reason="gap")

    return ObservationDecision(accept=True, reason="accepted")


__all__ = ["ObservationDecision", "validate_observation"]
