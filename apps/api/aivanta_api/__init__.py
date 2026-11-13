"""AIVANTA Relay API package."""
# Load .env into the process environment so the runtime settings read with os.getenv
# (N8N_*, AIVANTA_BRIDGE_*, LLM_*) honour the file in local development. Real environment
# variables always win (override=False); Docker Compose and the clouds set them directly.
try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # python-dotenv is optional outside development
    pass
