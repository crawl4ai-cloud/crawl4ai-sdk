"""Unit tests against a fake server (httpx.MockTransport): no key, no network, no cost."""

import asyncio
import json

import httpx
import pytest

import crawl4ai_cloud._client as client_module
from crawl4ai_cloud import (
    AsyncCrawl4AI,
    AuthenticationError,
    BadRequestError,
    BlockedError,
    Crawl4AI,
    PaymentRequiredError,
    RateLimitError,
    ServerError,
)

PAGE = {"ok": True, "markdown": "# Hi", "engine": "archive", "ms": 4, "text_len": 2, "new_field": 1}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Retries and polling do not wait in tests; the waits are recorded instead."""
    waits = []
    monkeypatch.setattr(client_module.time, "sleep", waits.append)
    return waits


@pytest.fixture(autouse=True)
def no_env_key(monkeypatch):
    monkeypatch.delenv("CRAWL4AI_API_KEY", raising=False)
    monkeypatch.delenv("CRAWL4AI_KEY", raising=False)


def fake(*answers):
    """Returns (client, requests): the client gets `answers` in order, one per request;
    `requests` records what it sent."""
    requests = []
    queue = list(answers)

    def handler(request):
        requests.append(request)
        return queue.pop(0)

    client = Crawl4AI("sk_test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return client, requests


def ndjson(*lines):
    return httpx.Response(200, content="\n".join(json.dumps(l) for l in lines) + "\n")


def test_key_from_env_and_missing(monkeypatch):
    with pytest.raises(AuthenticationError):
        Crawl4AI()
    monkeypatch.setenv("CRAWL4AI_KEY", "sk_old_name")
    assert Crawl4AI()._headers["Authorization"] == "Bearer sk_old_name"
    monkeypatch.setenv("CRAWL4AI_API_KEY", "sk_new_name")
    assert Crawl4AI()._headers["Authorization"] == "Bearer sk_new_name"


def test_scrape_sends_only_set_fields_and_reads_result():
    client, requests = fake(httpx.Response(200, json=PAGE, headers={"x-c4-cost": "0.500", "x-c4-balance": "99.5"}))
    page = client.scrape("https://example.com", format="md", parse={"links": True})

    sent = requests[0]
    assert sent.method == "POST" and sent.url == "https://api.crawl4ai.com/scrape"
    assert sent.headers["authorization"] == "Bearer sk_test"
    assert json.loads(sent.content) == {"url": "https://example.com", "format": "md", "parse": {"links": True}}
    assert page.ok and page.markdown == "# Hi" and page.engine == "archive" and page.html is None
    assert page.cost == 0.5 and page.balance == 99.5 and page.allowance_left is None
    assert page.raw["new_field"] == 1  # a field the SDK does not know is kept


@pytest.mark.parametrize(
    "answer, error_class, code",
    [
        (httpx.Response(402, json={"error": "no_credit", "message": "Out of credits", "actions": {"subscribe": "u"}}),
         PaymentRequiredError, "no_credit"),
        (httpx.Response(403, json={"ok": False, "reason": "login-wall"}), BlockedError, "login-wall"),
        (httpx.Response(401), AuthenticationError, None),
        (httpx.Response(422, text="missing field `url`"), BadRequestError, None),
        (httpx.Response(502, json={"ok": False, "reason": "no-answer"}), ServerError, "no-answer"),
    ],
)
def test_error_answers_become_exceptions(answer, error_class, code):
    client, requests = fake(answer)
    with pytest.raises(error_class) as caught:
        client.scrape("https://example.com")
    assert caught.value.status == answer.status_code and caught.value.code == code
    assert caught.value.message
    assert len(requests) == 1  # none of these is retried


def test_payment_error_keeps_message_and_actions():
    client, _ = fake(httpx.Response(402, json={"error": "no_credit", "message": "Out of credits", "actions": {"subscribe": "u"}}))
    with pytest.raises(PaymentRequiredError) as caught:
        client.search("x")
    assert str(caught.value) == "Out of credits" and caught.value.actions == {"subscribe": "u"}


def test_busy_is_retried_with_retry_after(no_sleep):
    client, requests = fake(
        httpx.Response(503, json={"ok": False, "reason": "busy"}, headers={"retry-after": "3"}),
        httpx.Response(200, json=PAGE),
    )
    assert client.scrape("https://example.com").ok
    assert len(requests) == 2 and no_sleep == [3.0]


def test_retries_stop_after_max_retries():
    client, requests = fake(*[httpx.Response(429, json={"error": "rate_limited"})] * 4)
    with pytest.raises(RateLimitError):
        client.search("x")
    assert len(requests) == 4  # the first try and 3 retries


def test_500_is_retried_for_search_but_not_for_starting_a_job():
    client, requests = fake(httpx.Response(500), httpx.Response(200, json={"results": []}))
    assert client.search("x").results == []
    assert len(requests) == 2

    client, requests = fake(httpx.Response(500), httpx.Response(200, json={"job_id": "j_1"}))
    with pytest.raises(ServerError):
        client.start_scrape_job(["https://example.com"])
    assert len(requests) == 1


def test_scrape_batch_yields_items_and_skips_the_summary():
    client, _ = fake(ndjson(
        {"url": "https://a.com", "ok": True, "result": PAGE, "cost": "0.500", "effort": 1},
        {"url": "https://b.com", "ok": False, "error": "upstream status 502"},
        {"summary": {"cost": "0.500", "priced": 1, "urls": 2}},
    ))
    items = list(client.scrape_batch(["https://a.com", "https://b.com"]))
    assert [i.url for i in items] == ["https://a.com", "https://b.com"]
    assert items[0].result.markdown == "# Hi" and items[0].cost == 0.5
    assert not items[1].ok and items[1].error == "upstream status 502" and items[1].result is None


def test_job_wait_and_results_read_every_page(no_sleep):
    client, requests = fake(
        httpx.Response(200, json={"job_id": "j_1", "status": "pending"}),
        httpx.Response(200, json={"job_id": "j_1", "status": "running", "counts": {"pending": 1}}),
        httpx.Response(200, json={"job_id": "j_1", "status": "done", "counts": {"done": 1, "error": 1}}),
        ndjson({"url": "https://a.com", "ok": True, "markdown": "# A", "seq": 0},
               {"url": "https://b.com", "ok": False, "error": {"class": "transient_exhausted", "detail": "http 502"}, "seq": 1}),
        httpx.Response(200, content=b""),
    )
    job = client.wait_scrape_job("j_1", poll_interval=1.5)
    assert job.status == "done" and job.counts == {"done": 1, "error": 1}
    assert no_sleep == [1.5, 1.5]

    items = list(client.get_scrape_job_results("j_1"))
    assert [i.url for i in items] == ["https://a.com", "https://b.com"]
    assert items[1].error["class"] == "transient_exhausted"
    assert [r.url.params.get("after") for r in requests[3:]] == ["0", "2"]


def test_wait_times_out(monkeypatch):
    clock = iter([0.0, 5.0, 11.0])
    monkeypatch.setattr(client_module.time, "monotonic", lambda: next(clock))
    client, _ = fake(*[httpx.Response(200, json={"status": "running"})] * 2)
    with pytest.raises(client_module.APITimeoutError):
        client.wait_scrape_job("j_1", timeout=10)


def test_wait_never_sleeps_past_its_timeout(monkeypatch, no_sleep):
    clock = iter([0.0, 9.0, 10.0])
    monkeypatch.setattr(client_module.time, "monotonic", lambda: next(clock))
    client, _ = fake(*[httpx.Response(200, json={"status": "running"})] * 2)
    with pytest.raises(client_module.APITimeoutError):
        client.wait_scrape_job("j_1", poll_interval=5, timeout=10)
    assert no_sleep == [1.0]  # 1 s left, not the full 5 s


def test_answer_sends_schema_as_json_text_and_deep_as_0():
    client, requests = fake(httpx.Response(200, json={
        "answered": True, "answer": {"text": '{"city":"Paris"}', "source": "crawl4ai", "sources": [{"title": "T", "url": "u"}]},
    }))
    result = client.answer("capital of France?", schema={"type": "object"}, deep=False)
    params = requests[0].url.params
    assert params["schema"] == '{"type":"object"}' and params["deep"] == "0" and params["q"] == "capital of France?"
    assert json.loads(result.answer.text) == {"city": "Paris"} and result.answer.sources[0].url == "u"


def test_serp_reads_nested_results():
    client, requests = fake(httpx.Response(200, json={
        "results": [{"position": 1, "domain": "example.com", "sitelinks": [{"title": "Docs", "url": "u"}]}],
        "blocks": ["organic"], "knowledge_panel": {"title": "X"},
    }))
    result = client.serp("crm", num=20, fresh=True)
    assert requests[0].url.params["num"] == "20" and requests[0].url.params["fresh"] == "1"
    assert result.results[0].sitelinks[0].title == "Docs" and result.raw["knowledge_panel"] == {"title": "X"}


def test_job_id_is_escaped_in_the_path():
    client, requests = fake(httpx.Response(200, json={"status": "done"}))
    client.get_scrape_job("a/b")
    assert requests[0].url.raw_path == b"/scrape/jobs/a%2Fb"


@pytest.mark.parametrize("job_id", ["", ".", ".."])
def test_job_id_that_is_a_folder_step_is_refused(job_id):
    client, requests = fake()
    with pytest.raises(ValueError):
        client.get_scrape_job(job_id)
    assert requests == []  # `..` would have sent the call to /scrape


def test_bypass_cache_is_sent():
    client, requests = fake(httpx.Response(200, json=PAGE))
    client.scrape("https://example.com", bypass_cache=True)
    assert json.loads(requests[0].content) == {"url": "https://example.com", "bypass_cache": True}


def test_timeout_holds_for_a_client_passed_in():
    requests = []
    transport = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200, json=PAGE))
    Crawl4AI("sk_test", timeout=60, http_client=httpx.Client(transport=transport)).scrape("https://example.com")
    assert requests[0].extensions["timeout"]["read"] == 60  # not httpx's default of 5 s


def test_retry_reads_usage():
    client, _ = fake(httpx.Response(200, json={"job_id": "j_1", "retrying": 2, "usage": {"units": 2}}))
    result = client.retry_scrape_job("j_1")
    assert result.retrying == 2 and result.usage == {"units": 2}


def test_timeout_in_the_middle_of_a_stream_is_a_timeout():
    class StopsAfterOneLine(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"url": "https://a.com", "ok": true}\n'
            raise httpx.ReadTimeout("no more bytes")

    client, _ = fake(httpx.Response(200, stream=StopsAfterOneLine()))
    items = client.scrape_batch(["https://a.com", "https://b.com"])
    assert next(items).url == "https://a.com"
    with pytest.raises(client_module.APITimeoutError):
        next(items)


def test_async_client_retries_and_streams(monkeypatch):
    waits = []

    async def record_wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr(client_module.asyncio, "sleep", record_wait)
    answers = [
        httpx.Response(503, json={"reason": "busy"}, headers={"retry-after": "2"}),
        httpx.Response(200, json=PAGE),
        ndjson({"url": "https://a.com", "ok": True, "result": PAGE}, {"summary": {"urls": 1}}),
    ]

    async def run():
        transport = httpx.MockTransport(lambda request: answers.pop(0))
        async with AsyncCrawl4AI("sk_test", http_client=httpx.AsyncClient(transport=transport)) as client:
            page = await client.scrape("https://example.com")
            items = [i async for i in client.scrape_batch(["https://a.com"])]
        return page, items

    page, items = asyncio.run(run())
    assert page.markdown == "# Hi" and [i.url for i in items] == ["https://a.com"] and waits == [2.0]
