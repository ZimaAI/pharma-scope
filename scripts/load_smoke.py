#!/usr/bin/env python3
"""Small isolated PostgreSQL/API load probe, not a production capacity claim."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import threading
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if not os.environ.get("PHARMA_TEST_DATABASE_URL"):
    raise SystemExit("Set PHARMA_TEST_DATABASE_URL to an isolated integration database")
spec = importlib.util.spec_from_file_location("postgres_integration", ROOT / "backend/tests/test_postgres_integration.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
seconds = float(os.environ.get("PHARMA_LOAD_SECONDS", "30"))
concurrency = int(os.environ.get("PHARMA_LOAD_CONCURRENCY", "6"))
generator = module.postgres_env.__wrapped__()
env = next(generator)
try:
    module.bootstrap(env)
    with tempfile.TemporaryDirectory(prefix="pharmascope-load-") as directory:
        with module.api_process(env, Path(directory)) as origin:
            with httpx.Client(base_url=origin, trust_env=False) as client:
                workspace = module.login(client, env)
                cookies, headers = dict(client.cookies), {"X-CSRF-Token": client.headers["X-CSRF-Token"]}
            children = Path(f"/proc/{os.getpid()}/task/{os.getpid()}/children").read_text().split()
            pid = next(int(child) for child in children if b"uvicorn" in Path(f"/proc/{child}/cmdline").read_bytes())
            stop = threading.Event()
            memory = []
            def sample():
                while not stop.wait(.1):
                    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            memory.append(int(line.split()[1]))
            sampler = threading.Thread(target=sample)
            sampler.start()
            start = time.monotonic()
            deadline = start + seconds
            def requests(worker):
                samples, errors, writes = [], [], 0
                index = 0
                with httpx.Client(base_url=origin, cookies=cookies, headers=headers, trust_env=False, timeout=15) as client:
                    while time.monotonic() < deadline:
                        began = time.monotonic()
                        try:
                            if index % 4 == 0:
                                response = client.post(f"/api/v1/workspaces/{workspace}/drugs", json={"display_name": f"Load probe {worker}/{index}"})
                                expected = 201
                                writes += response.status_code == 201
                            else:
                                response = client.get(f"/api/v1/workspaces/{workspace}/drugs?limit=20")
                                expected = 200
                            if response.status_code != expected:
                                errors.append("HTTP_" + str(response.status_code))
                        except httpx.TransportError as exc:
                            errors.append(type(exc).__name__)
                        samples.append(time.monotonic() - began)
                        index += 1
                return samples, errors, writes
            try:
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    results = list(executor.map(requests, range(concurrency)))
            finally:
                stop.set()
                sampler.join(timeout=2)
            elapsed = time.monotonic() - start
            latencies = sorted(value for samples, _, _ in results for value in samples)
            errors = [error for _, failures, _ in results for error in failures]
            created = sum(writes for _, _, writes in results)
            with httpx.Client(base_url=origin, cookies=cookies, trust_env=False) as client:
                visible, cursor = 0, None
                while True:
                    params = {"limit": 100}
                    if cursor: params["cursor"] = cursor
                    response = client.get(f"/api/v1/workspaces/{workspace}/drugs", params=params)
                    assert response.status_code == 200
                    payload = response.json()
                    visible += len(payload["items"])
                    cursor = payload.get("next_cursor")
                    if not cursor: break
            result = {"kind": "small_isolated_smoke_not_capacity_acceptance", "database": "PostgreSQL 16, isolated schema", "duration_seconds": round(elapsed, 3), "concurrency": concurrency, "requests": len(latencies), "errors": len(errors), "error_types": sorted(set(errors)), "writes": created, "visible_records": visible, "requests_per_second": round(len(latencies)/elapsed, 2), "latency_p50_ms": round(statistics.median(latencies)*1000, 2), "latency_p95_ms": round(latencies[int(len(latencies)*.95)]*1000, 2), "latency_max_ms": round(max(latencies)*1000, 2), "api_peak_rss_mib": round(max(memory, default=0)/1024, 2)}
            output = ROOT / "outputs/verification/load-smoke.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
            if errors or visible != created:
                raise SystemExit("Load smoke detected errors or missing records")
finally:
    try:
        next(generator)
    except StopIteration:
        pass
