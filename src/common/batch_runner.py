"""Thin helpers around the Anthropic Message Batches API (submit, wait, cancel, collect).

Deliberately knows nothing about the pipeline: no DB, no pages, no pricing. Callers (screen.py) own the persistence of
the batch id and the decision what to do with a request that got no usable result. Limits and behaviour are those of
platform.claude.com/docs/en/build-with-claude/batch-processing (read 2026-11-05): up to 100,000 requests or 256 MB per
batch, most batches finish within an hour and none later than 24 hours, results stay available for 29 days, result
order is not guaranteed (match on custom_id), and one failed request never fails the others.
"""
import json
import time
from dataclasses import dataclass
from types import SimpleNamespace

# The documented ceilings are 100,000 requests / 256 MB. Stay well below both: a smaller batch is cheaper to lose.
MAX_REQUESTS_PER_BATCH = 10_000
MAX_BYTES_PER_BATCH = 150 * 1024 * 1024
DEFAULT_POLL_SECONDS = 30.0
CANCEL_WAIT_SECONDS = 120.0


@dataclass
class BatchResult:
    custom_id: str
    kind: str  # succeeded | errored | expired | canceled | no_tool_use | refused
    tool_input: dict | None = None
    usage: SimpleNamespace | None = None
    error: str | None = None
    stop_reason: str | None = None  # the model's stop_reason for a succeeded request ("refusal" => kind "refused")

    @property
    def usable(self) -> bool:
        return self.kind == "succeeded" and self.tool_input is not None


def estimate_request_bytes(request: dict) -> int:
    return len(json.dumps(request, ensure_ascii=False).encode("utf-8"))


def split_into_batches(requests: list[dict], max_requests: int | None = None,
                       max_bytes: int | None = None) -> list[list[dict]]:
    """Consecutive chunks, each within both limits. A single request larger than max_bytes gets a chunk of its own
    (the API would reject it; that is reported there, not hidden here)."""
    max_requests = MAX_REQUESTS_PER_BATCH if max_requests is None else max_requests
    max_bytes = MAX_BYTES_PER_BATCH if max_bytes is None else max_bytes
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_bytes = 0
    for request in requests:
        size = estimate_request_bytes(request)
        if current and (len(current) >= max_requests or current_bytes + size > max_bytes):
            chunks.append(current)
            current, current_bytes = [], 0
        current.append(request)
        current_bytes += size
    if current:
        chunks.append(current)
    return chunks


def create_batch(client, requests: list[dict]) -> str:
    return client.messages.batches.create(requests=requests).id


def wait_for_batch(client, batch_id: str, timeout_seconds: float, poll_seconds: float = DEFAULT_POLL_SECONDS,
                   already_elapsed: float = 0.0, sleep=time.sleep, monotonic=time.monotonic, log=print) -> str:
    """Polls until the batch has ended ("ended") or `timeout_seconds` have passed since the batch was CREATED
    ("timeout"; `already_elapsed` is how long it has already been running when this call starts, e.g. after a
    restart). A failed status request is logged and retried at the next poll - it never ends the wait early."""
    started = monotonic() - already_elapsed
    while True:
        try:
            batch = client.messages.batches.retrieve(batch_id)
            counts = batch.request_counts
            log(f"  [batch] {batch_id}: {batch.processing_status} (processing {counts.processing}, succeeded "
                f"{counts.succeeded}, errored {counts.errored}, canceled {counts.canceled}, expired {counts.expired})")
            if batch.processing_status == "ended":
                return "ended"
        except Exception as exc:  # noqa: BLE001 - a flaky status call must not abandon a batch that is running
            log(f"  [batch] {batch_id}: status check failed ({type(exc).__name__}: {exc}) - will retry")
        if monotonic() - started >= timeout_seconds:
            return "timeout"
        sleep(poll_seconds)


def cancel_batch(client, batch_id: str, poll_seconds: float = DEFAULT_POLL_SECONDS, max_wait: float = CANCEL_WAIT_SECONDS,
                 sleep=time.sleep, monotonic=time.monotonic, log=print) -> bool:
    """Asks for cancellation and waits (bounded) until the batch is reported ended. Requests that finished before the
    cancel keep their results. Returns whether the batch is ended."""
    try:
        client.messages.batches.cancel(batch_id)
        log(f"  [batch] {batch_id}: cancel requested")
    except Exception as exc:  # noqa: BLE001
        log(f"  [batch] {batch_id}: cancel request failed ({type(exc).__name__}: {exc})")
    deadline = monotonic() + max_wait
    while monotonic() < deadline:
        try:
            if client.messages.batches.retrieve(batch_id).processing_status == "ended":
                return True
        except Exception:  # noqa: BLE001
            pass
        sleep(poll_seconds)
    return False


def fetch_results(client, batch_id: str) -> dict[str, BatchResult]:
    """{custom_id: BatchResult} for every request the batch returned. A succeeded request without a tool_use block
    (refusal, truncated) is reported as no_tool_use so that the caller treats it like any other missing result."""
    out: dict[str, BatchResult] = {}
    for entry in client.messages.batches.results(batch_id):
        result = entry.result
        kind = result.type
        if kind != "succeeded":
            error = getattr(result, "error", None)
            out[entry.custom_id] = BatchResult(entry.custom_id, kind, error=str(error) if error is not None else None)
            continue
        message = result.message
        tool_use = next((block for block in message.content if block.type == "tool_use"), None)
        usage = SimpleNamespace(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_creation_input_tokens=getattr(message.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(message.usage, "cache_read_input_tokens", 0) or 0,
        )
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "refusal":  # PROJECT_LOG 4.132: the model declined; its tool_use block (if any) is empty
            out[entry.custom_id] = BatchResult(entry.custom_id, "refused", usage=usage, error="stop_reason=refusal",
                                               stop_reason=stop_reason)
        elif tool_use is None:
            out[entry.custom_id] = BatchResult(entry.custom_id, "no_tool_use", usage=usage,
                                               error=f"stop_reason={getattr(message, 'stop_reason', None)}")
        else:
            out[entry.custom_id] = BatchResult(entry.custom_id, "succeeded", tool_input=dict(tool_use.input), usage=usage)
    return out
