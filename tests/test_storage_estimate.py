from gui.services.storage_estimate import (
    CAPTURE_IMAGE_BYTES,
    SECONDARY_DATA_RESERVE_FACTOR,
    assess_schedule_storage,
    estimate_storage_bytes,
)


def test_storage_estimate_reserves_space_for_secondary_data():
    assert CAPTURE_IMAGE_BYTES == 7_600_000
    assert SECONDARY_DATA_RESERVE_FACTOR == 2
    assert estimate_storage_bytes(10) == 152_000_000


def test_storage_assessment_distinguishes_capacity_and_missing_telemetry():
    assert assess_schedule_storage(
        10, {"free_bytes": 151_999_999}
    )["status"] == "insufficient"
    assert assess_schedule_storage(
        10, {"free_bytes": 152_000_000}
    )["status"] == "sufficient"
    assert assess_schedule_storage(10, None)["status"] == "unverified"
