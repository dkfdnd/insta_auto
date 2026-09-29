"""Conservative delays for explicit external collection/search operations."""
import random
import time

import requests


def request_pause():
    """Rest before each operation, including the first request and retries."""
    time.sleep(random.uniform(1.0, 3.0))


class PacedSession(requests.Session):
    def send(self, request, **kwargs):
        # send also covers redirects made by requests itself.
        request_pause()
        return super().send(request, **kwargs)


def ytdlp_pacing_args():
    return ['--sleep-requests', '1', '--sleep-interval', '1',
            '--max-sleep-interval', '3', '--retry-sleep', '2']
