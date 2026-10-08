#!/usr/bin/env python3
"""Ask GrowthOS to verify its local audit chain and anchor the current head into Chrysalis.

GrowthOS no longer treats a file/webhook as the production trust anchor. Chrysalis is canonical.
The GrowthOS API records the Chrysalis receipt in `chrysalis_anchors` and its local audit chain.
"""
import json
import os
import sys
import httpx

base = os.environ.get("GROWTHOS_URL", "http://127.0.0.1:8080").rstrip("/")
key = os.environ.get("GROWTHOS_API_KEY", "")
if not key:
    sys.exit("GROWTHOS_API_KEY is required")
r = httpx.post(base + "/v1/chrysalis/anchor/audit", headers={"X-API-Key": key}, timeout=30)
if r.status_code >= 400:
    sys.exit(f"anchor failed: HTTP {r.status_code} {r.text[:300]}")
print(json.dumps(r.json(), sort_keys=True))
