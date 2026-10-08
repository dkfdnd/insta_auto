"""Measure provider probing separately from local candidate verification."""
from contextlib import contextmanager
import time


def candidate_probe_seconds(settings, platform_remaining, overall_remaining, pending_count):
    """Give a ranked candidate a useful slice within all acquisition caps.

    Dividing 300 seconds between twelve links used to give each about 25
    seconds, including extraction and pacing. Real partial downloads were
    repeatedly killed before completion. Give up to 60 seconds as the useful
    floor; lower configured/per-platform/overall limits remain authoritative.
    Later candidates can be deferred instead of turning every link into a
    premature timeout. A single request never gets the whole platform budget.
    """
    if min(platform_remaining,overall_remaining) <= 0:
        return 0
    share = platform_remaining / max(1,pending_count)
    useful_slice = min(60, settings.source_candidate_download_budget)
    return max(0,min(settings.source_candidate_download_budget,
                     max(useful_slice,share),platform_remaining,overall_remaining))


@contextmanager
def charge_platform_probe(seconds, platform):
    """Charge only acquisition, including pacing/failures, to its platform.

    OCR, CLIP and local AI queue waits happen outside this scope. The caller
    retains its overall round deadline, so verification time remains bounded
    by the existing work and service timeout limits.
    """
    started = time.monotonic()
    try:
        yield
    finally:
        seconds[platform] = seconds.get(platform, 0) + time.monotonic() - started
