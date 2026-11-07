#!/usr/bin/env python
"""Layered Gemini connectivity diagnosis. Run from backend/ with the venv active:

    python scripts\\diagnose_gemini.py            # all layers (the last one sends ONE tiny real Gemini request)
    python scripts\\diagnose_gemini.py --skip-sdk # network layers only, no API request

Layers: proxy settings -> DNS -> TCP 443 -> TLS certificate -> HTTPS request -> Gemini SDK call.
The first failing layer tells you where the problem is. Credentials in proxy URLs and the API key are never printed.
"""
import argparse
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
HOST, PORT = "generativelanguage.googleapis.com", 443
PROXY_VARS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE")


def mask_proxy(value: str) -> str:
    """scheme://host:port only - user:password@ is stripped."""
    p = urlparse(value if "://" in value else "http://" + value)
    return f"{p.scheme}://{p.hostname}:{p.port}" if p.hostname and p.port else (f"{p.scheme}://{p.hostname}" if p.hostname else "<unparseable>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-sdk", action="store_true", help="do not send a real Gemini request")
    args = ap.parse_args()
    results: list[tuple[str, bool, str]] = []

    def record(name, ok, note):
        results.append((name, ok, note))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {note}")

    print("1. Proxy / certificate environment (values masked)")
    found = False
    for v in PROXY_VARS:
        if os.environ.get(v):
            found = True
            print(f"     {v} = {mask_proxy(os.environ[v]) if 'PROXY' in v and v != 'NO_PROXY' else os.environ[v]}")
    system = {k: mask_proxy(v) for k, v in urllib.request.getproxies().items()}
    if system:
        found = True
        print(f"     system/OS proxies seen by Python: {system}")
    if not found:
        print("     none set")

    print(f"2. DNS for {HOST}")
    addrs = []
    try:
        t = time.monotonic()
        infos = socket.getaddrinfo(HOST, PORT, type=socket.SOCK_STREAM)
        addrs = sorted({(i[0], i[4][0]) for i in infos}, key=lambda x: x[0].value)
        record("DNS", True, f"{len(addrs)} address(es) in {1000 * (time.monotonic() - t):.0f} ms: " + ", ".join(a for _, a in addrs[:4]))
    except OSError as exc:
        record("DNS", False, f"{exc}. Check internet/VPN/DNS server; try `nslookup {HOST}`.")

    print(f"3. TCP connect to port {PORT} (direct, ignores proxies)")
    good = None
    if not addrs:
        record("TCP", False, "skipped (DNS failed)")
    else:
        for fam, ip in addrs[:4]:
            label = "IPv6" if fam == socket.AF_INET6 else "IPv4"
            try:
                socket.create_connection((ip, PORT), timeout=8).close()
                record(f"TCP {label}", True, ip)
                good = good or ip
            except OSError as exc:
                record(f"TCP {label}", False, f"{ip}: {exc}")
        if not good:
            print("     (If your network REQUIRES a proxy, direct connections failing is expected; layer 5 uses the proxy.)")

    print("4. TLS handshake and certificate")
    if not good:
        record("TLS", False, "skipped (no direct TCP connection)")
    else:
        try:
            with socket.create_connection((good, PORT), timeout=8) as raw, ssl.create_default_context().wrap_socket(raw, server_hostname=HOST) as tls:
                issuer = dict(x[0] for x in tls.getpeercert().get("issuer", ()))
                record("TLS", True, f"{tls.version()}, certificate issuer: {issuer.get('organizationName', '?')} / {issuer.get('commonName', '?')}")
        except ssl.SSLCertVerificationError as exc:
            record("TLS", False, f"certificate verification failed: {exc.verify_message}. Something between you and Google is re-signing HTTPS "
                                 "(antivirus, proxy, corporate firewall). Set SSL_CERT_FILE to a CA bundle that includes its root certificate.")
        except (ssl.SSLError, OSError) as exc:
            record("TLS", False, str(exc))

    print("5. HTTPS request via Python's default settings (honours proxies). Any HTTP status counts as success.")
    try:
        with urllib.request.urlopen(f"https://{HOST}/", timeout=15) as r:
            record("HTTPS", True, f"HTTP {r.status}")
    except urllib.error.HTTPError as exc:
        record("HTTPS", True, f"HTTP {exc.code} (server reachable)")
    except (urllib.error.URLError, OSError) as exc:
        record("HTTPS", False, str(getattr(exc, "reason", exc)))

    print("6. Gemini SDK request (the same code path the app uses)")
    if args.skip_sdk:
        print("     skipped (--skip-sdk)")
    else:
        try:
            from app.agents import llm
            print(f"     status: {llm.ai_status()['message']}")
            res = llm.check()
            record("Gemini SDK", res["ok"], f"model={res['model']} kind={res['kind']}: {res['message']}")
            for line in res.get("detail", []):
                print(f"       cause chain: {line}")
        except Exception as exc:  # noqa: BLE001 - diagnostic tool must not crash
            record("Gemini SDK", False, f"{type(exc).__name__}: {exc}")

    failed = [r for r in results if not r[1]]
    print("\nSummary:", "all layers passed" if not failed else f"first failing layer = {failed[0][0]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
