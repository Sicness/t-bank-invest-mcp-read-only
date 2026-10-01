"""Tests for the pinned Russian Trusted Root CA used by T-API over TLS."""

import hashlib
import ssl

import pytest

from tbank_invest_mcp.server import CA_FILE, CA_SHA256, _ssl_context


class TestPinnedCa:
    def test_ca_file_shipped(self):
        assert CA_FILE.exists(), f"{CA_FILE} is missing from the package"

    def test_ca_file_matches_pinned_fingerprint(self):
        der = ssl.PEM_cert_to_DER_cert(CA_FILE.read_text())
        assert hashlib.sha256(der).hexdigest() == CA_SHA256

    def test_context_trusts_the_root(self):
        names = [
            value
            for cert in _ssl_context().get_ca_certs()
            for rdn in cert.get("subject", ())
            for key, value in rdn
            if key == "commonName"
        ]
        assert "Russian Trusted Root CA" in names

    def test_context_keeps_default_trust_store(self):
        """Pinning must add to public CAs, not replace them."""
        assert len(_ssl_context().get_ca_certs()) > 1


class TestFingerprintGuard:
    def test_rejects_a_substituted_ca(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TBANK_CA_BUNDLE", raising=False)
        monkeypatch.setattr(
            "tbank_invest_mcp.server.CA_SHA256", "0" * 64
        )
        with pytest.raises(RuntimeError, match="Refusing to trust it"):
            _ssl_context()

    def test_bundle_override_skips_the_pin(self, monkeypatch):
        import certifi

        monkeypatch.setenv("TBANK_CA_BUNDLE", certifi.where())
        monkeypatch.setattr("tbank_invest_mcp.server.CA_SHA256", "0" * 64)
        _ssl_context()  # must not raise — the override replaces the pinned root
