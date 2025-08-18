import os
import logging


def load_env() -> None:
    """Load environment variables from a .env file if available.
    Prefer python-dotenv when installed; otherwise, fall back to a simple reader.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
        return
    except Exception:
        pass

    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.abspath(env_path)
    if os.path.exists(env_path):
        try:
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key.strip(), value.strip())
        except Exception:
            # Non-fatal
            pass


# Load env early
load_env()

# Logging configuration
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, log_level, logging.INFO),
)
logger = logging.getLogger(__name__)

# Reduce noisy libraries
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)


class Config:
    """Application configuration with simple API endpoint selection."""

    # Telegram Bot Configuration
    BOT_TOKEN: str | None = os.getenv("BOT_TOKEN")
    ALLOWED_USER_ID: int = int(os.getenv("ALLOWED_USER_ID", "0"))

    # LTA Fantasy API Configuration
    X_SESSION_TOKEN: str = os.getenv("X_SESSION_TOKEN", "").strip()
    
    # Universal polling configuration
    POLL_SECS: int = int(os.getenv("POLL_SECS", "30"))  # Base polling interval for all phases
    
    # Stale detection and backoff (applied to all polling phases)
    MAX_STALE_POLLS: int = int(os.getenv("MAX_STALE_POLLS", "12"))
    BACKOFF_MULTIPLIER: float = float(os.getenv("BACKOFF_MULTIPLIER", "2.0"))
    MAX_POLL_SECS: int = int(os.getenv("MAX_POLL_SECS", "900"))

    # API Endpoint Configuration
    LTA_API_URL: str = os.getenv("LTA_API_URL", "https://api.ltafantasy.com").strip()

    @classmethod
    def validate_config(cls) -> None:
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN environment variable is required")
        if cls.ALLOWED_USER_ID == 0:
            raise ValueError("ALLOWED_USER_ID environment variable is required")
        if not cls.X_SESSION_TOKEN:
            logger.warning("X_SESSION_TOKEN not configured - use /auth to provide it")

    @classmethod
    def get_api_base_url(cls) -> str:
        logger.info(f"Using API endpoint: {cls.LTA_API_URL}")
        return cls.LTA_API_URL


# Initialize and expose commonly used constants to match legacy API
config = Config()
config.validate_config()
BASE = config.get_api_base_url()
BOT_TOKEN = config.BOT_TOKEN
ALLOWED_USER_ID = config.ALLOWED_USER_ID
X_SESSION_TOKEN = config.X_SESSION_TOKEN

# Universal polling configurations
POLL_SECS = config.POLL_SECS
MAX_STALE_POLLS = config.MAX_STALE_POLLS
BACKOFF_MULTIPLIER = config.BACKOFF_MULTIPLIER
MAX_POLL_SECS = config.MAX_POLL_SECS

# Legacy compatibility - removed phase-specific variables
