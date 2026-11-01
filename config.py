"""Shared backend timing and protocol constants."""

import os

PROTOCOL_VERSION = 4
DRAFT_CONTEXT_SECONDS = 1.35
DRAFT_INTERVAL_SECONDS = 0.9
MIN_CAPTURE_SECONDS = 0.7
MAX_DECODE_SECONDS = 8.0
PHRASE_LIMIT_SECONDS = 7.8
MAX_BUFFER_SECONDS = 9.8
MAX_BUFFER_FRAMES = 260


def agent_concurrency():
    """Bound provider work by the existing twelve-job capacity."""
    try:
        value = int(os.getenv("AGENT_MAX_CONCURRENT_JOBS", "3"))
    except ValueError:
        raise ValueError("AGENT_MAX_CONCURRENT_JOBS must be an integer from 1 to 12.") from None
    if not 1 <= value <= 12:
        raise ValueError("AGENT_MAX_CONCURRENT_JOBS must be an integer from 1 to 12.")
    return value
