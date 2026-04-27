import os

os.environ.setdefault("MONGODB_URL", "mongodb://unused-for-tests")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("DRAGONFLY_URL", "redis://localhost:6379/15")
os.environ.setdefault("TYPESENSE_URL", "http://localhost:8108")
os.environ.setdefault("TYPESENSE_API_KEY", "test-typesense-key")
os.environ.setdefault("LIVEKIT_API_KEY", "test-livekit-key")
os.environ.setdefault("LIVEKIT_API_SECRET", "test-livekit-secret")
os.environ.setdefault("JWT_SECRET_KEY", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET_KEY", "test-refresh-secret")
os.environ.setdefault("MESSAGE_CURSOR_SECRET_KEY", "test-message-cursor-secret")
os.environ.setdefault("MESSAGE_ENCRYPTION_ACTIVE_KEY_ID", "v1")
os.environ.setdefault(
    "MESSAGE_ENCRYPTION_KEYS",
    '{"v1":"MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="}',
)

pytest_plugins = ["tests.fixtures.app"]
