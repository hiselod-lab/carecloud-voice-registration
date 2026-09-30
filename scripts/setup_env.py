"""Generate credentials locally. Existing .env is never overwritten."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if path.exists():
    raise SystemExit(".env already exists; edit it manually. Nothing was changed.")
token = secrets.token_urlsafe(32)
secret = secrets.token_urlsafe(32)
text = (root / ".env.example").read_text()
text = text.replace("API_BEARER_TOKEN=\n", f"API_BEARER_TOKEN={token}\n")
text = text.replace("VAPI_WEBHOOK_SECRET=\n", f"VAPI_WEBHOOK_SECRET={secret}\n")
path.write_text(text)
try:
    path.chmod(0o600)
except OSError:
    pass
print("Created .env with unique API and webhook credentials. Keep this file private.")
print("Open .env locally and paste API_BEARER_TOKEN into the dashboard Connect dialog.")
print("Use fictional patient details only. DEMO_LOG_PAYLOADS remains false by default.")
