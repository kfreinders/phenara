from scripts.analysis.queue import AnalysisQueue


def capture(capture_id: str, *, status: str = "succeeded"):
    return {
        "capture_id": capture_id,
        "scheduled_at": capture_id,
        "status": status,
        "image_path": f"capture_{capture_id}.jpg",
    }


def test_queue_derives_pending_images_from_successful_captures(tmp_path):
    queue = AnalysisQueue(tmp_path / "analysis")
    captures = [
        capture("2026-07-22T12:00:00+00:00"),
        capture("2026-07-22T13:00:00+00:00", status="failed"),
    ]

    assert queue.pending(captures) == [captures[0]]


def test_successful_analysis_is_not_queued_again(tmp_path):
    queue = AnalysisQueue(tmp_path / "analysis")
    captures = [capture("2026-07-22T12:00:00+00:00")]
    queue.record(
        capture_id=captures[0]["capture_id"],
        image_path=captures[0]["image_path"],
        status="running",
        message="started",
    )
    queue.record(
        capture_id=captures[0]["capture_id"],
        image_path=captures[0]["image_path"],
        status="succeeded",
        message="finished",
        duration_seconds=12.5,
    )

    assert queue.pending(captures) == []
    assert queue.summary(captures) == {
        "total": 1,
        "succeeded": 1,
        "failed": 0,
        "running": 0,
        "pending": 0,
    }


def test_failed_analysis_is_retried_at_most_three_times(tmp_path):
    queue = AnalysisQueue(tmp_path / "analysis")
    captures = [capture("2026-07-22T12:00:00+00:00")]

    for attempt in range(3):
        queue.record(
            capture_id=captures[0]["capture_id"],
            image_path=captures[0]["image_path"],
            status="running",
            message=f"attempt {attempt + 1}",
        )
        queue.record(
            capture_id=captures[0]["capture_id"],
            image_path=captures[0]["image_path"],
            status="failed",
            message="failed",
        )

    assert queue.pending(captures) == []
    assert queue.summary(captures)["failed"] == 1


def test_retryable_failure_is_still_reported_as_pending(tmp_path):
    queue = AnalysisQueue(tmp_path / "analysis")
    captures = [capture("2026-07-22T12:00:00+00:00")]
    queue.record(
        capture_id=captures[0]["capture_id"],
        image_path=captures[0]["image_path"],
        status="running",
        message="attempt 1",
    )
    queue.record(
        capture_id=captures[0]["capture_id"],
        image_path=captures[0]["image_path"],
        status="failed",
        message="failed",
    )

    summary = queue.summary(captures)
    assert summary["failed"] == 0
    assert summary["pending"] == 1
