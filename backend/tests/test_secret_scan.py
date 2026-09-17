"""Credential detection, and — more importantly — what it must NOT fire on.

A guardrail that masks ordinary text gets switched off, and a guardrail that is off
protects nothing. The false-positive half of this file is therefore the half that
matters: every case below was chosen because it looks credential-shaped and is not.
"""
from app.guardrails import pii_ko, secret_scan


def _types(text):
    return sorted({f["type"] for f in secret_scan.detect(text)})


# ── found ────────────────────────────────────────────────────────────────────────

def test_aws_access_key_id():
    assert _types("export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE") == ["AWS 액세스 키"]


def test_pem_private_key_header():
    assert _types("-----BEGIN RSA PRIVATE KEY-----\nMIIEow...") == ["개인키"]


def test_github_and_slack_tokens():
    assert _types("token ghp_" + "a" * 36) == ["GitHub 토큰"]
    assert _types("xoxb-123456789012-abcdefghijkl") == ["Slack 토큰"]


def test_jwt():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1g"
    assert _types(f"Authorization: Bearer {jwt}") == ["JWT"]


def test_db_url_masks_only_the_password():
    url = "postgresql://svc:s3cr3tpw@db-host:5432/app"
    findings = secret_scan.detect(url)
    assert [f["type"] for f in findings] == ["DB 접속정보"]
    assert findings[0]["match"] == "s3cr3tpw"
    masked = pii_ko.mask(url)
    # the host and database survive — that is what makes the finding actionable
    assert "db-host:5432/app" in masked and "s3cr3tpw" not in masked


def test_named_credential_assignment():
    assert _types('api_key = "abcd1234efgh"') == ["자격증명"]
    assert _types("client_secret: Xy9-Kq2LmPz0") == ["자격증명"]


# ── not found (false-positive guards) ────────────────────────────────────────────

def test_uuid_and_git_sha_are_not_credentials():
    assert _types("id 550e8400-e29b-41d4-a716-446655440000") == []
    assert _types("commit 9fe7408a1b2c3d4e5f60718293a4b5c6d7e8f901") == []


def test_placeholders_are_not_credentials():
    for line in ('password = "changeme"',
                 'api_key = "<your-api-key>"',
                 'password = "${DB_PASSWORD}"',
                 'secret_key = "example-value"',
                 'auth_token = "$(VAULT_TOKEN)"'):
        assert _types(line) == [], line


def test_the_word_password_in_prose_is_not_a_credential():
    assert _types("Reset your password by email if you forget it.") == []


def test_short_values_are_not_credentials():
    # `WHERE password = 'x'` is SQL, not a leak
    assert _types("WHERE password = 'x'") == []


def test_masked_text_rescans_clean():
    """Masked text reaches the audit log; scanning it again must find nothing new."""
    once = pii_ko.mask('api_key = "abcd1234efgh" and AKIAIOSFODNN7EXAMPLE')
    assert "abcd1234efgh" not in once and "AKIAIOSFODNN7EXAMPLE" not in once
    assert pii_ko.mask(once) == once


# ── integration with the PII guardrail ───────────────────────────────────────────

def test_secrets_travel_the_pii_pipeline(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "mask")
    text = "key AKIAIOSFODNN7EXAMPLE for 010-1234-5678"
    out, findings, blocked = pii_ko.apply(text)
    assert not blocked
    assert sorted({f["type"] for f in findings}) == ["AWS 액세스 키", "휴대전화"]
    assert "AKIAIOSFODNN7EXAMPLE" not in out


def test_block_mode_blocks_on_a_secret_alone(monkeypatch):
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "block")
    _, findings, blocked = pii_ko.apply("-----BEGIN PRIVATE KEY-----")
    assert blocked and [f["type"] for f in findings] == ["개인키"]


def test_collection_scope_still_tightens(monkeypatch):
    """The per-collection tightening shipped for PII governs secrets too."""
    monkeypatch.setenv("PII_GUARDRAIL_MODE", "mask")
    with pii_ko.scope("block"):
        _, _, blocked = pii_ko.apply("AKIAIOSFODNN7EXAMPLE")
    assert blocked
