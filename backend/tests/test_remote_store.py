from app.services import remote_store as rs


def test_disabled_without_url(monkeypatch):
    monkeypatch.setattr(rs, "_dsn", lambda: "")
    assert rs.enabled() is False
    assert rs.put("k", {"a": 1}) is False
    assert rs.get("k") == (None, None)


def test_put_get_roundtrip(monkeypatch):
    store: dict[str, tuple] = {}

    class FakeCursor:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class FakeConn:
        def execute(self, sql, params=None):
            text = " ".join(sql.split())
            if text.startswith("CREATE TABLE"):
                return FakeCursor(None)
            if text.startswith("INSERT INTO"):
                key, payload = params
                store[key] = payload
                return FakeCursor(None)
            if text.startswith("SELECT"):
                key = params[0]
                if key not in store:
                    return FakeCursor(None)
                return FakeCursor((store[key], None))
            return FakeCursor(None)

        def commit(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(rs, "enabled", lambda: True)
    monkeypatch.setattr(rs, "_dsn", lambda: "postgresql://example")
    monkeypatch.setattr(rs, "_connect", lambda: FakeConn())
    rs._SCHEMA_READY = False
    assert rs.put("preferences", {"nav_hidden": []}) is True
    value, _ = rs.get("preferences")
    assert value == {"nav_hidden": []}
