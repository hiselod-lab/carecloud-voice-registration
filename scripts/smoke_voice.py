"""Synthetic HTTP contract test, NOT a real voice or speech-recognition test.

Run against your own demo deployment: python scripts/smoke_voice.py http://127.0.0.1:8000
Reads VAPI_WEBHOOK_SECRET/API_BEARER_TOKEN from .env. Creates one fictional patient.
"""
import json
import os
import sys
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
import httpx
from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
trust_env = urlsplit(base).hostname not in {"localhost", "127.0.0.1", "::1"}
secret = os.getenv("VAPI_WEBHOOK_SECRET", "")
api_token = os.getenv("API_BEARER_TOKEN", "")
if not secret or not api_token:
    raise SystemExit("Set VAPI_WEBHOOK_SECRET and API_BEARER_TOKEN in .env first.")
call_id = "synthetic-smoke-" + str(uuid4())
patient = json.loads((root / "voice/sample-patient.json").read_text())


def tool(name, arguments, user_text, timestamp, tool_id=None):
    tool_id = tool_id or str(uuid4())
    payload = {"message": {"type": "tool-calls", "call": {"id": call_id},
        "artifact": {"messages": [{"role": "user", "message": user_text, "time": timestamp, "endTime": timestamp + 1}]},
        "toolCallList": [{"id": tool_id, "type": "function", "function": {"name": name, "arguments": arguments}}]}}
    response = httpx.post(base + "/voice/webhook", json=payload, headers={"Authorization": "Bearer " + secret}, timeout=20, trust_env=trust_env)
    response.raise_for_status()
    item = response.json()["results"][0]
    if "error" in item:
        raise RuntimeError(item["error"])
    return json.loads(item["result"])


tool("update_registration", {"fields": patient}, "Here are my fictional registration details", 1)
review = tool("review_registration", {}, "Everything has been provided", 2)
print("FULL READBACK:", review["readback"])
confirmation = {"review_token": review["review_token"], "confirmation": "Yes, please save"}
receipt_id = str(uuid4())
saved = tool("confirm_registration", confirmation, "Yes, please save", 3, receipt_id)
retry = tool("confirm_registration", confirmation, "Yes, please save", 3, receipt_id)
assert saved["patient_id"] == retry["patient_id"]
response = httpx.get(base + "/patients/" + saved["patient_id"], headers={"Authorization": "Bearer " + api_token}, trust_env=trust_env)
response.raise_for_status()
print("COMMITTED SYNTHETIC PATIENT JSON:")
print(json.dumps(response.json(), indent=2))
print("PASS: update, full review, explicit confirmation, durable read, idempotent retry")
