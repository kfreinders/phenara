import asyncio

import pytest
from pydantic import ValidationError

from gui.app import app
from gui.routes.schedule_api import ActivationRequest
from gui.routes.scheduler import CancellationRequest, ExperimentDeletionRequest
from gui.services.schedule_form import ScheduleFormData


def request(method: str, path: str, headers=None, body: bytes = b""):
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(key.lower().encode(), value.encode()) for key, value in (headers or [])],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    return start["status"], dict(start["headers"])


def test_mutating_api_requests_require_the_browser_request_marker():
    status, headers = request("POST", "/api/schedule/draft")

    assert status == 403
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"x-frame-options"] == b"DENY"
    policy = headers[b"content-security-policy"]
    assert b"frame-ancestors 'none'" in policy
    assert b"img-src 'self' data: blob:" in policy


@pytest.mark.parametrize("length", ["invalid", "-1", "1000001"])
def test_api_rejects_invalid_or_excessive_content_lengths(length):
    status, _ = request(
        "POST",
        "/api/schedule/draft",
        [("content-length", length), ("x-phenara-request", "1")],
    )

    assert status == 413


@pytest.mark.parametrize(
    "model,payload",
    [
        (ActivationRequest, {"draft_hash": "a" * 64, "unexpected": True}),
        (CancellationRequest, {"schedule_hash": "a" * 64, "unexpected": True}),
        (
            ExperimentDeletionRequest,
            {
                "schedule_hash": "a" * 64,
                "experiment_name": "Finished plants",
                "unexpected": True,
            },
        ),
        (
            ScheduleFormData,
            {
                "mode": "every",
                "experiment_name": "Security test",
                "start_date": "2026-07-24",
                "num_days": 1,
                "replicates": 1,
                "replicate_interval_seconds": 0,
                "every_start": "09:00",
                "every_end": "10:00",
                "every_step_minutes": 30,
                "unexpected": True,
            },
        ),
    ],
)
def test_api_models_reject_unexpected_fields(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_production_api_documentation_is_not_exposed():
    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None
