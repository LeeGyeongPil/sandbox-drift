import urllib.error
import urllib.request

from sandbox_drift import worker


def test_http_error_is_closed_and_classified(monkeypatch):
    closed = []

    class Err(urllib.error.HTTPError):
        def close(self):
            closed.append(True)
            super().close()

    def fake_urlopen(*args, **kwargs):
        raise Err(worker.RESERVED_URL, 403, "Forbidden", {}, None)

    monkeypatch.setenv(worker.PROXY_VARIABLES[0], "http://127.0.0.1:1")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    status, detail = worker.probe_proxy_reserved_host({}, lambda s: s)
    assert closed == [True]
    assert status == worker.classify_http(403)
