# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the ssh-audit report parser (no network, no target).

``stock-image`` is the shape ssh-audit returns for the current image
(broken SHA-1 MACs and an NSA-suspect ECDSA host key, both fail-rated,
and no Edwards-curve host key); ``hardened`` is the shape the twelfth
check requires.  Together they are the parser's RED/GREEN pair.
"""

from __future__ import annotations

from typing import Any

from validate.ssh_audit import parse

STOCK: dict[str, Any] = {
    "kex": [
        {"algorithm": "mlkem768x25519-sha256", "notes": {"info": ["ok"]}},
        {
            "algorithm": "curve25519-sha256",
            "notes": {
                "warn": ["does not provide protection against post-quantum attacks"]
            },
        },
    ],
    "key": [
        {
            "algorithm": "ecdsa-sha2-nistp256",
            "notes": {"fail": ["nsa curve"], "warn": ["rng"]},
        },
    ],
    "enc": [{"algorithm": "aes256-gcm@openssh.com", "notes": {"info": []}}],
    "mac": [
        {"algorithm": "hmac-sha1-etm@openssh.com", "notes": {"fail": ["broken SHA-1"]}},
        {"algorithm": "hmac-sha2-256", "notes": {"warn": ["encrypt-and-MAC"]}},
    ],
    "fingerprints": [
        {"hostkey": "ecdsa-sha2-nistp256", "hash_alg": "SHA256", "hash": "x"},
        {"hostkey": "ecdsa-sha2-nistp256", "hash_alg": "MD5", "hash": "y"},
    ],
}

HARDENED: dict[str, Any] = {
    "kex": [{"algorithm": "mlkem768x25519-sha256", "notes": {"info": []}}],
    "key": [{"algorithm": "ssh-mldsa44-ed25519@openssh.com", "notes": {"info": []}}],
    "enc": [{"algorithm": "aes256-gcm@openssh.com", "notes": {"info": []}}],
    "mac": [{"algorithm": "hmac-sha2-256-etm@openssh.com", "notes": {"info": []}}],
    # ssh-audit cannot complete a post-quantum-only handshake, so a real
    # report of this server carries no fingerprint; posture keys on the
    # offered "key" algorithms above, not on fingerprints.
    "fingerprints": [],
}


def test_stock_image_has_fail_rated_algorithms() -> None:
    audit = parse(STOCK)
    assert audit.has_failures()
    assert set(audit.failed) == {"ecdsa-sha2-nistp256", "hmac-sha1-etm@openssh.com"}


def test_stock_image_offers_no_post_quantum_host_key() -> None:
    audit = parse(STOCK)
    assert "ssh-mldsa44-ed25519@openssh.com" not in audit.offered["key"]


def test_hardened_report_passes_the_posture_check() -> None:
    audit = parse(HARDENED)
    assert not audit.has_failures()
    assert "ssh-mldsa44-ed25519@openssh.com" in audit.offered["key"]
    assert audit.is_post_quantum_kex()


def test_classical_key_exchange_is_flagged_not_post_quantum() -> None:
    audit = parse(STOCK)
    assert not audit.is_post_quantum_kex()
    assert audit.kex_not_pq == ("curve25519-sha256",)


def test_offered_lists_are_populated_per_class() -> None:
    audit = parse(STOCK)
    assert "hmac-sha1-etm@openssh.com" in audit.offered["mac"]
    assert audit.offered["key"] == ("ecdsa-sha2-nistp256",)
