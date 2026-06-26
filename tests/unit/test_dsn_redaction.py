"""Unit tests for DSN redaction in logging."""

from __future__ import annotations

from web.backend.veritas_web.logging_config import redact_dsn


def test_redact_dsn_with_password():
    """Test DSN with password is properly redacted."""
    dsn = "postgresql://user:secretpass@host:5432/dbname"
    result = redact_dsn(dsn)

    assert "password=***" in result
    assert "user=user" in result
    assert "host=host" in result
    assert "port=5432" in result
    assert "db=dbname" in result
    assert "env=postgresql" in result
    # Password must not appear in output
    assert "secretpass" not in result


def test_redact_dsn_without_password():
    """Test DSN without password still shows redacted marker."""
    dsn = "postgresql://user@host:5432/dbname"
    result = redact_dsn(dsn)

    assert "password=***" in result
    assert "user=user" in result
    assert "host=host" in result
    assert "port=5432" in result
    assert "db=dbname" in result


def test_redact_dsn_without_port():
    """Test DSN without explicit port."""
    dsn = "postgresql://user:pass@host/dbname"
    result = redact_dsn(dsn)

    assert "password=***" in result
    assert "port=unknown" in result
    assert "user=user" in result
    assert "host=host" in result


def test_redact_dsn_with_query_params():
    """Test DSN with query parameters."""
    dsn = "postgresql://user:secretpass@host:5432/dbname?sslmode=require"
    result = redact_dsn(dsn)

    assert "password=***" in result
    assert "user=user" in result
    assert "host=host" in result
    # Query params should not appear in output
    assert "sslmode" not in result
    # Actual password must not appear
    assert "secretpass" not in result


def test_redact_dsn_empty_string():
    """Test empty DSN returns safe fallback."""
    dsn = ""
    result = redact_dsn(dsn)

    assert "password=***" in result
    assert "env=unknown" in result
    assert "user=unknown" in result
    assert "host=unknown" in result


def test_redact_dsn_no_database():
    """Test DSN without database path."""
    dsn = "postgresql://user:pass@host:5432"
    result = redact_dsn(dsn)

    assert "password=***" in result
    assert "db=unknown" in result


def test_redact_dsn_complex_password():
    """Test DSN with special characters in password."""
    dsn = "postgresql://user:p@ss:w0rd!@host:5432/dbname"
    result = redact_dsn(dsn)

    assert "password=***" in result
    # The actual password must not appear
    assert "p@ss:w0rd!" not in result
    assert "w0rd" not in result


def test_redact_dsn_output_format():
    """Test output format matches expected pattern."""
    dsn = "postgresql://testuser:testpass@dbhost:5433/testdb"
    result = redact_dsn(dsn)

    # Should start with "Database configured:"
    assert result.startswith("Database configured:")

    # Should contain all expected fields
    assert "env=" in result
    assert "user=" in result
    assert "host=" in result
    assert "port=" in result
    assert "db=" in result
    assert "password=***" in result


def test_redact_dsn_no_plaintext_password_pattern():
    """Verify no pattern matching user:pass@host in output."""
    import re

    dsn = "postgresql://admin:supersecret@production-db:5432/myapp"
    result = redact_dsn(dsn)

    # Pattern that would indicate plaintext password in DSN format
    plaintext_pattern = r":\S+@\S+:"
    assert not re.search(plaintext_pattern, result), (
        f"Output contains plaintext password pattern: {result}"
    )
