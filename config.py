import os

from dotenv import load_dotenv

load_dotenv()
basedir = os.path.abspath(os.path.dirname(__file__))


def as_bool(value):
    if value:
        return value.lower() in ["true", "yes", "on", "1"]
    return False


class Config:
    """Base configuration class. All settings loaded from environment variables."""

    # database options — SQLite by default for local dev (no Postgres required);
    # override with DATABASE_URL env var or use docker-compose for production.
    DATABASE_URL = (
        os.environ.get("DATABASE_URL")
        or f"sqlite:///{os.path.join(basedir, 'pybpm.db')}"
    )
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Configuration settings
    ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")
    if ENVIRONMENT == "development":
        SQLALCHEMY_ECHO = as_bool(os.environ.get("SQL_DEBUG", "true"))

    SECRET_KEY = os.environ.get("SECRET_KEY", "fallback-secret-change-in-production")
    JWT_EXPIRATION_HOURS = int(os.environ.get("JWT_EXPIRATION_HOURS", "24"))

    ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", "1"))
    AUTODISCOVER_PATHS = as_bool(os.environ.get("AUTODISCOVER_PATHS", "false"))

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    CREATE_START_MSG = as_bool(os.environ.get("CREATE_START_MSG", "false"))

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False
    TESTING = False


class TestingConfig(Config):
    DEBUG = True
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


def get_config_by_name(name: str) -> type[Config]:
    """Return the configuration class for a given env name."""
    mapping = {
        "development": DevelopmentConfig,
        "testing": TestingConfig,
        "production": Config,
    }
    cls = mapping.get(name)
    if cls is None:
        raise ValueError(f"Unknown config name: {name}")
    return cls
