from core.database_dsn import database_url_async, database_url_sync, parse_database_url


def test_parse_railway_style_url() -> None:
    parts = parse_database_url(
        "postgresql://user:p%40ss@containers-us-west-123.railway.app:6543/railway?sslmode=require"
    )
    assert parts.host.endswith("railway.app")
    assert parts.port == 6543
    assert parts.user == "user"
    assert parts.password == "p@ss"
    assert parts.database == "railway"
    assert ("sslmode", "require") in parts.query


def test_build_async_and_sync_dsn() -> None:
    parts = parse_database_url("postgres://bot:secret@db.example.com:5432/oukhelpbot")
    assert database_url_async(parts).startswith("postgresql+asyncpg://")
    assert database_url_sync(parts).startswith("postgresql+psycopg://")
    assert "db.example.com:5432/oukhelpbot" in database_url_async(parts)


def test_empty_url_raises() -> None:
    try:
        parse_database_url("")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


if __name__ == "__main__":
    test_parse_railway_style_url()
    test_build_async_and_sync_dsn()
    test_empty_url_raises()
    print("database_dsn: ok")
