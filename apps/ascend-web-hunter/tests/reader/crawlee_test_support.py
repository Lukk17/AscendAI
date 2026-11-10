"""Shared fakes for the crawlee tier tests."""

from datetime import timedelta

from crawlee.statistics import FinalStatistics


def final_statistics(requests_finished: int) -> FinalStatistics:
    """Crawl statistics reporting *requests_finished* handled requests.

    The crawlee tier treats a crawl that handled no request as a failure, so every fake
    crawler has to report what a real crawl would have reported.
    """
    return FinalStatistics(
        requests_finished=requests_finished,
        requests_failed=0 if requests_finished else 1,
        retry_histogram=[],
        request_avg_failed_duration=None,
        request_avg_finished_duration=None,
        requests_finished_per_minute=0.0,
        requests_failed_per_minute=0.0,
        request_total_duration=timedelta(),
        requests_total=1,
        crawler_runtime=timedelta(),
    )
