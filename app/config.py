"""Runtime configuration. Never commit the generated .env file."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"true", "1", "yes"}


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./data/patients.db")
    api_bearer_token: str = os.getenv("API_BEARER_TOKEN", "")
    vapi_webhook_secret: str = os.getenv("VAPI_WEBHOOK_SECRET", "")
    vapi_public_key: str = os.getenv("VAPI_PUBLIC_KEY", "")
    vapi_assistant_id: str = os.getenv("VAPI_ASSISTANT_ID", "")
    demo_log_payloads: bool = env_bool("DEMO_LOG_PAYLOADS")
    environment: str = os.getenv("ENVIRONMENT", "development")


settings = Settings()
