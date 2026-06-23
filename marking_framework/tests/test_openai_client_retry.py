import scripts.openai_client as oc


def test_read_timeout_is_retried(monkeypatch):
    calls = {"n": 0}

    def flaky_post(url, api_key, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("The read operation timed out")
        return {"ok": True}

    monkeypatch.setattr(oc, "_post_json", flaky_post)
    monkeypatch.setattr(oc.time, "sleep", lambda s: None)
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "3")
    result = oc._post_openai_with_compat("https://x", "key", {"model": "m"})
    assert result == {"ok": True}
    assert calls["n"] == 2


def test_read_timeout_exhausts_budget(monkeypatch):
    def always_timeout(url, api_key, payload):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(oc, "_post_json", always_timeout)
    monkeypatch.setattr(oc.time, "sleep", lambda s: None)
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "2")
    try:
        oc._post_openai_with_compat("https://x", "key", {"model": "m"})
        assert False, "should raise"
    except RuntimeError as exc:
        assert "network error" in str(exc)
