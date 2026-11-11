from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # our own services
    database_url: str = "postgresql+psycopg://stemchub:stemchub@db:5432/stemchub"
    redis_url: str = "redis://redis:6379/0"
    cache_dir: str = "/cache"
    public_url: str = "http://localhost:8090"

    # login
    admin_username: str = ""  # first admin, created on start if there are no users yet
    admin_password: str = ""
    session_hours: int = 12
    cookie_secure: bool = False  # True as soon as the app is served over HTTPS
    allow_simple_passwords: bool = False  # LOCAL TESTING ONLY: drops the password rules (allows root / root)
    webhook_token: str = ""  # shared secret for /api/hooks/nextcloud; empty = webhook disabled

    # OMERO
    omero_host: str = "omero-server"
    omero_port: int = 4064
    omero_user: str = "root"
    omero_password: str = ""
    omero_project: str = "INDUZELL"
    omero_web_public_url: str = "http://localhost:4080"

    # Nextcloud
    nextcloud_url: str = "http://nextcloud"
    nextcloud_user: str = "admin"
    nextcloud_password: str = ""
    nextcloud_root: str = "INDUZELL"  # folder watched for new files
    nextcloud_poll_seconds: int = 60

    # eLabFTW
    elab_url: str = "https://elabftw:8080"  # used by our containers
    elab_public_url: str = "https://localhost:8443"  # used in links for the browser
    elab_api_key: str = ""
    elab_verify_tls: bool = True
    elab_sync_seconds: int = 120
    elab_writeback: bool = True

    # analysis
    segmenter: str = "cellpose"  # "cellpose" or "classic"
    nucleus_diameter_um: float = 10.0
    ethd_min_z: float = 6.0  # dead = EthD this many robust SDs above background ...
    ethd_min_ratio: float = 1.5  # ... and at least this many times brighter than background
    write_rois: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
