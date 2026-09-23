#!/usr/bin/env python3
"""Run the checked-in Nginx proxy in isolation, including trusted test TLS/SSE.

Requires a running replay API. Uses dedicated loopback ports, an ephemeral TLS
certificate and a temporary prefix; never touches the system Nginx or its sites.
"""
from pathlib import Path
import http.cookiejar
import json
import os
import re
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("PHARMA_PROXY_TEST_API", "http://127.0.0.1:18180")
HTTP_PORT = int(os.environ.get("PHARMA_PROXY_TEST_HTTP_PORT", "18480"))
TLS_PORT = int(os.environ.get("PHARMA_PROXY_TEST_TLS_PORT", "18443"))
for port in (HTTP_PORT, TLS_PORT):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
with urllib.request.urlopen(API + "/healthz", timeout=5) as response:
    if json.load(response).get("mode") != "demo":
        raise SystemExit("This smoke test requires an explicit replay API")
with tempfile.TemporaryDirectory(prefix="pharmascope-proxy-") as directory:
    tmp = Path(directory)
    cert, key = tmp / "cert.pem", tmp / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    site = (ROOT / "deploy/pharmascope.nginx.conf").read_text()
    site = site.replace("listen 80;", f"listen 127.0.0.1:{HTTP_PORT};").replace("listen [::]:80;", "")
    site = site.replace("listen 443 ssl;", f"listen 127.0.0.1:{TLS_PORT} ssl;").replace("listen [::]:443 ssl;", "")
    site = site.replace("https://pharmascope.zimagent.top", f"https://localhost:{TLS_PORT}").replace("server_name pharmascope.zimagent.top;", "server_name localhost;")
    site = site.replace("/var/www/pharmascope/current", str(ROOT / "frontend/nextjs/out"))
    site = site.replace("/etc/letsencrypt/live/pharmascope.zimagent.top/fullchain.pem", str(cert)).replace("/etc/letsencrypt/live/pharmascope.zimagent.top/privkey.pem", str(key))
    site = re.sub(r"    include /etc/letsencrypt/options-ssl-nginx.conf;", "    ssl_protocols TLSv1.2 TLSv1.3;", site)
    site = re.sub(r"    ssl_dhparam .*;", "", site)
    site = site.replace("http://127.0.0.1:18180", API).replace("/var/log/nginx/pharmascope.access.log", str(tmp / "access.log")).replace("/var/log/nginx/pharmascope.error.log", str(tmp / "error.log"))
    config = tmp / "nginx.conf"
    config.write_text(f"pid {tmp}/nginx.pid;\nerror_log {tmp}/master.log;\nevents {{ worker_connections 64; }}\nhttp {{ access_log {tmp}/default-access.log; client_body_temp_path {tmp}/body; proxy_temp_path {tmp}/proxy; fastcgi_temp_path {tmp}/fastcgi; uwsgi_temp_path {tmp}/uwsgi; scgi_temp_path {tmp}/scgi; include /etc/nginx/mime.types;\n{site}\n}}\n")
    command = ["nginx", "-p", directory, "-c", str(config)]
    subprocess.run(command + ["-t"], check=True)
    process = subprocess.Popen(command + ["-g", "daemon off;"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        context = ssl.create_default_context(cafile=str(cert))
        cookies = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(cookies))
        origin = f"https://localhost:{TLS_PORT}"
        for _ in range(50):
            try:
                response = opener.open(origin + "/healthz", timeout=1)
                response.close()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise RuntimeError("isolated Nginx failed to start")
        for endpoint in ("/healthz", "/readyz", "/"):
            with opener.open(origin + endpoint, timeout=5) as response:
                body = response.read().decode()
                assert response.status == 200
                if endpoint == "/":
                    asset = re.search(r'src="([^" ]+\.js[^" ]*)"', body)
                    assert asset, "static JS reference missing"
                    with opener.open(origin + asset.group(1), timeout=5) as script:
                        assert script.status == 200 and script.read(), "static script missing"
        with opener.open(f"http://localhost:{HTTP_PORT}/healthz", timeout=5) as response:
            assert response.url == origin + "/healthz", "HTTPS redirect failed"
        try:
            opener.open(origin + "/api/v1/auth/me", timeout=5)
        except urllib.error.HTTPError as error:
            assert error.code == 401 and error.headers.get("x-request-id")
            assert error.headers.get("Cache-Control") == "no-store"
            assert error.headers.get("X-Content-Type-Options") == "nosniff"
        else:
            raise AssertionError("authentication boundary missing")
        login = urllib.request.Request(origin + "/api/v1/auth/login", data=json.dumps({"email": "analyst@pharmascope.invalid", "password": os.environ.get("PHARMA_DEMO_PASSWORD", "demo")}).encode(), headers={"Content-Type": "application/json"})
        with opener.open(login, timeout=5) as response:
            assert response.status == 200
        endpoint = "/api/v1/workspaces/dee59b72-2cb2-5255-934c-b44a3fd8911c/research/runs/0ea32fa2-01c1-5aed-a9b1-d0fa7bd00b8a/events"
        with opener.open(origin + endpoint, timeout=5) as response:
            assert response.headers.get("Content-Type", "").startswith("text/event-stream")
            assert response.headers.get("X-Accel-Buffering") == "no"
            for _ in range(20):
                if response.readline().startswith(b"data:"):
                    break
            else:
                raise AssertionError("no persisted SSE event received")
        print("PASS isolated Nginx: trusted TLS, HTTPS redirect, static HTML/JS, health/ready proxy, auth boundary and authenticated SSE")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
