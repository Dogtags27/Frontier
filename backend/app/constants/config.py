"""Process settings. Hosts come from the environment, not from call sites."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
_ENV_FILES = tuple(path for path in (REPO / ".env", BACKEND / ".env") if path.exists())
_DEFAULT_MANIFEST = REPO / "data" / "extract" / "manifest.json"
_BUNDLED_MANIFEST = BACKEND / "manifest.json"


def database_url(url: str) -> str:
    """Add sslmode when the URL omits it. Local hosts stay unencrypted."""
    if not url or "sslmode=" in url:
        return url
    local = any(host in url for host in ("@localhost", "@127.0.0.1", "@postgres"))
    mode = "disable" if local else "require"
    return url + ("&" if "?" in url else "?") + f"sslmode={mode}"


class Settings(BaseSettings):
    """One settings object. Empty strings mean the value was not provided."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILES or None,
        extra="ignore",
    )

    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_password: str = ""
    database_url: str = ""
    r2_endpoint: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "frontier-research-papers"
    openai_api_key: str = ""
    chat_model: str = "gpt-4.1-mini"
    embed_model: str = "text-embedding-3-small"
    supabase_url: str = ""
    # Public https origin of this API, used in OAuth discovery. Blank: derived from the request.
    public_url: str = ""
    supabase_jwt_issuer: str = ""
    supabase_jwt_audience: str = "authenticated"
    admin_emails: str = ""
    corpus_graph: str = "frontier_corpus"
    manifest_path: str = ""
    query_timeout_ms: int = 120_000
    rate_backend: str = "auto"
    rate_capacity_student: int = 60
    rate_capacity_supervisor: int = 60
    rate_capacity_admin: int = 180
    rate_ip_capacity: int = 600
    rate_auth_capacity: int = 10
    rate_refill_per_sec: float = 1
    rate_auth_refill_per_sec: float = 0.2
    rate_window_sec: int = 60
    max_agent_concurrency: int = 2
    daily_tokens_student: int = 200_000
    daily_tokens_supervisor: int = 200_000
    daily_tokens_admin: int = 1_000_000
    daily_usd_student: float = 10
    daily_usd_supervisor: float = 10
    daily_usd_admin: float = 10
    daily_usd_org: float = 20
    monthly_usd: float = 50
    chat_input_usd_per_mtok: float = 0.40
    chat_output_usd_per_mtok: float = 1.60
    embed_usd_per_mtok: float = 0.02
    embed_cache_ttl_sec: int = 86_400
    max_body_bytes: int = 1_048_576
    worker_concurrency: int = 4
    work_lease_sec: int = 30
    work_sweep_sec: int = 30
    work_attempts: int = 3
    work_hint_key: str = "wq:hints"
    agent_max_steps: int = 8
    gap_neighbor_weight: float = 1
    gap_evidence_weight: float = 2
    gap_distance_weight: float = 0.5
    gap_min_support: int = 2
    gap_result_limit: int = 5
    chat_max_words: int = 1000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    def tier_capacity(self, role: str) -> int:
        table = {
            "student": self.rate_capacity_student,
            "supervisor": self.rate_capacity_supervisor,
            "admin": self.rate_capacity_admin,
        }
        return table.get(role, self.rate_capacity_student)

    def daily_token_cap(self, role: str) -> int:
        table = {
            "student": self.daily_tokens_student,
            "supervisor": self.daily_tokens_supervisor,
            "admin": self.daily_tokens_admin,
        }
        return table.get(role, self.daily_tokens_student)

    def daily_usd_cap(self, role: str) -> float:
        table = {
            "student": self.daily_usd_student,
            "supervisor": self.daily_usd_supervisor,
            "admin": self.daily_usd_admin,
        }
        return table.get(role, self.daily_usd_student)

    @property
    def manifest(self) -> Path:
        if self.manifest_path:
            return Path(self.manifest_path)
        if _DEFAULT_MANIFEST.exists():
            return _DEFAULT_MANIFEST
        return _BUNDLED_MANIFEST

    @property
    def postgres_url(self) -> str:
        return database_url(self.database_url)

    @property
    def jwt_issuer(self) -> str:
        if self.supabase_jwt_issuer:
            return self.supabase_jwt_issuer.rstrip("/")
        return self.supabase_url.rstrip("/") + "/auth/v1"

    @property
    def jwks_url(self) -> str:
        return self.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"

    @property
    def admin_email_set(self) -> set[str]:
        return {normalize_email(part) for part in self.admin_emails.split(",") if part.strip()}


def normalize_email(value: str) -> str:
    """Trim and lowercase. Comparisons and the admin list both use this form."""
    return value.strip().lower()


@lru_cache
def get_settings() -> Settings:
    return Settings()
