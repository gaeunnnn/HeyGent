from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os


# 로컬 개발에서는 .env 파일을 가장 많이 쓰므로 기본 위치를 명시해 둔다.
DEFAULT_ENV_FILE = Path(".env")


@dataclass(slots=True)
class Settings:
    """애플리케이션 전역 설정이다.

    현재 백본은 개발/실사용 코드를 나누기보다,
    같은 서버 구조를 환경 변수만 바꿔서 재사용하는 방향을 기본값으로 둔다.
    """

    app_name: str = "HeyGent AI Backbone"
    api_prefix: str = "/ai/api/v1"
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    log_level: str = "info"
    postgres_dsn: str | None = None
    postgres_migrations_enabled: bool = True
    api_base_url: str | None = None
    openai_api_key: str | None = None
    openai_rest_api_base_url: str = "https://api.openai.com/v1"
    openai_response_model: str = "gpt-5.4"
    openai_embedding_model: str = "text-embedding-3-small"
    backend_base_url: str = "http://127.0.0.1:8080"
    backend_auth_verify_url: str = "http://127.0.0.1:8080/internal/ai/auth/validate"
    backend_bridge_auth_verify_url: str = "http://127.0.0.1:8080/internal/bridge/auth/validate"
    backend_memory_timeout_seconds: float = 5.0
    backend_tool_timeout_seconds: float = 10.0
    memory_recall_llm_planner_enabled: bool = False
    internal_service_token: str | None = None
    redis_url: str | None = None
    cors_allowed_origins: list[str] = field(default_factory=list)
    cors_allowed_methods: list[str] = field(default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    cors_allowed_headers: list[str] = field(
        default_factory=lambda: ["Authorization", "Content-Type", "X-Workspace-Key"]
    )
    cors_allow_credentials: bool = True
    cors_max_age_seconds: int = 600
    ws_connection_ttl_seconds: int = 60
    ws_auth_first_message_timeout_seconds: float = 10.0
    ws_allowed_origins: list[str] = field(default_factory=list)
    ws_auth_rate_limit_max_failures: int = 5
    ws_auth_rate_limit_window_seconds: int = 60
    task_projection_ttl_seconds: int = 3600
    task_projection_max_events: int = 200
    task_execution_queue_enabled: bool = False
    task_execution_worker_count: int = 2
    task_execution_lease_seconds: int = 300
    task_execution_poll_interval_seconds: float = 0.5
    public_session_limit_per_user: int = 10
    agent_model_request_timeout_seconds: float = 300.0
    agent_model_stream_timeout_seconds: float = 300.0
    agent_loop_default_max_iterations: int = 90
    agent_loop_worker_default_max_iterations: int = 80
    agent_loop_max_iterations: int = 120
    work_execution_max_iterations: int = 24
    agent_secret_encryption_key: str | None = None
    # DEPRECATED: 단일 공유 토큰 시절 잔재. 현재는 backend /internal/bridge/auth/validate 로 검증.
    bridge_token: str | None = None

    def resolved_api_base_url(self) -> str:
        """CLI 와 외부 클라이언트가 공통으로 사용할 기본 API 주소를 계산한다."""

        if self.api_base_url:
            return self.api_base_url.rstrip("/")
        normalized_prefix = "/" + self.api_prefix.strip("/")
        return f"http://{self.host}:{self.port}{normalized_prefix}"

def load_dotenv_values(env_file: Path | None = None) -> dict[str, str]:
    """간단한 .env 파서를 직접 제공한다.

    별도 라이브러리 없이도 로컬 실행과 CLI, 테스트가 같은 설정 파일을 읽게 하려는 목적이다.
    운영 환경에서는 실제 OS 환경 변수가 항상 우선한다.
    """

    target = env_file or DEFAULT_ENV_FILE
    if not target.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        value = raw_value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _read_env(name: str, default, dotenv_values: dict[str, str]):
    """OS 환경 변수를 최우선으로 보고, 없을 때만 .env 값을 사용한다."""

    if name in os.environ:
        return os.environ[name]
    return dotenv_values.get(name, default)


def _parse_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value, *, default: int) -> int:
    if value in {None, ""}:
        return default
    return int(value)


def _parse_float(value, *, default: float) -> float:
    if value in {None, ""}:
        return default
    return float(value)


def _parse_scopes(value) -> list[str]:
    if value in {None, ""}:
        return []
    return [scope.strip() for scope in str(value).split(",") if scope.strip()]


def _parse_csv(value) -> list[str]:
    if value in {None, ""}:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _parse_optional_path(value) -> Path | None:
    if value in {None, ""}:
        return None
    return Path(str(value))


def get_settings() -> Settings:
    """현재 실행 시점의 설정을 읽어 Settings 객체로 반환한다.

    lifespan 과 CLI 에서 같은 함수를 공유해도 환경 차이를 반영할 수 있게
    일부러 전역 캐시를 두지 않는다.
    """

    dotenv_values = load_dotenv_values()
    return Settings(
        app_name=_read_env("HEYGENT_APP_NAME", "HeyGent AI Backbone", dotenv_values),
        api_prefix=_read_env("HEYGENT_API_PREFIX", "/ai/api/v1", dotenv_values),
        host=_read_env("HEYGENT_HOST", "127.0.0.1", dotenv_values),
        port=_parse_int(_read_env("HEYGENT_PORT", 8000, dotenv_values), default=8000),
        reload=_parse_bool(_read_env("HEYGENT_RELOAD", "false", dotenv_values)),
        log_level=_read_env("HEYGENT_LOG_LEVEL", "info", dotenv_values),
        postgres_dsn=_read_env("HEYGENT_POSTGRES_DSN", None, dotenv_values),
        postgres_migrations_enabled=_parse_bool(
            _read_env("HEYGENT_POSTGRES_MIGRATIONS_ENABLED", "true", dotenv_values),
            default=True,
        ),
        api_base_url=_read_env("HEYGENT_API_BASE_URL", None, dotenv_values),
        openai_api_key=_read_env("HEYGENT_OPENAI_API_KEY", None, dotenv_values),
        openai_rest_api_base_url=_read_env("HEYGENT_OPENAI_REST_API_BASE_URL", "https://api.openai.com/v1", dotenv_values),
        openai_response_model=_read_env("HEYGENT_OPENAI_RESPONSE_MODEL", "gpt-5.4", dotenv_values),
        openai_embedding_model=_read_env("HEYGENT_OPENAI_EMBEDDING_MODEL", "text-embedding-3-small", dotenv_values),
        backend_base_url=_read_env("HEYGENT_BACKEND_BASE_URL", "http://127.0.0.1:8080", dotenv_values),
        backend_auth_verify_url=_read_env(
            "HEYGENT_BACKEND_AUTH_VERIFY_URL",
            "http://127.0.0.1:8080/internal/ai/auth/validate",
            dotenv_values,
        ),
        backend_bridge_auth_verify_url=_read_env(
            "HEYGENT_BACKEND_BRIDGE_AUTH_VERIFY_URL",
            "http://127.0.0.1:8080/internal/bridge/auth/validate",
            dotenv_values,
        ),
        backend_memory_timeout_seconds=_parse_float(
            _read_env("HEYGENT_BACKEND_MEMORY_TIMEOUT_SECONDS", 5.0, dotenv_values),
            default=5.0,
        ),
        backend_tool_timeout_seconds=_parse_float(
            _read_env("HEYGENT_BACKEND_TOOL_TIMEOUT_SECONDS", 10.0, dotenv_values),
            default=10.0,
        ),
        memory_recall_llm_planner_enabled=_parse_bool(
            _read_env("HEYGENT_MEMORY_RECALL_LLM_PLANNER_ENABLED", "false", dotenv_values),
            default=False,
        ),
        internal_service_token=_read_env("HEYGENT_INTERNAL_SERVICE_TOKEN", None, dotenv_values),
        redis_url=_read_env("HEYGENT_REDIS_URL", None, dotenv_values),
        cors_allowed_origins=_parse_csv(_read_env("HEYGENT_CORS_ALLOWED_ORIGINS", "", dotenv_values)),
        cors_allowed_methods=_parse_csv(
            _read_env("HEYGENT_CORS_ALLOWED_METHODS", "GET,POST,PUT,PATCH,DELETE,OPTIONS", dotenv_values)
        ),
        cors_allowed_headers=_parse_csv(
            _read_env("HEYGENT_CORS_ALLOWED_HEADERS", "Authorization,Content-Type,X-Workspace-Key", dotenv_values)
        ),
        cors_allow_credentials=_parse_bool(
            _read_env("HEYGENT_CORS_ALLOW_CREDENTIALS", "true", dotenv_values),
            default=True,
        ),
        cors_max_age_seconds=_parse_int(
            _read_env("HEYGENT_CORS_MAX_AGE_SECONDS", 600, dotenv_values),
            default=600,
        ),
        ws_connection_ttl_seconds=_parse_int(
            _read_env("HEYGENT_WS_CONNECTION_TTL_SECONDS", 60, dotenv_values),
            default=60,
        ),
        ws_auth_first_message_timeout_seconds=_parse_float(
            _read_env("HEYGENT_WS_AUTH_FIRST_MESSAGE_TIMEOUT_SECONDS", 10.0, dotenv_values),
            default=10.0,
        ),
        ws_allowed_origins=_parse_csv(_read_env("HEYGENT_WS_ALLOWED_ORIGINS", "", dotenv_values)),
        ws_auth_rate_limit_max_failures=_parse_int(
            _read_env("HEYGENT_WS_AUTH_RATE_LIMIT_MAX_FAILURES", 5, dotenv_values),
            default=5,
        ),
        ws_auth_rate_limit_window_seconds=_parse_int(
            _read_env("HEYGENT_WS_AUTH_RATE_LIMIT_WINDOW_SECONDS", 60, dotenv_values),
            default=60,
        ),
        task_projection_ttl_seconds=_parse_int(
            _read_env("HEYGENT_TASK_PROJECTION_TTL_SECONDS", 3600, dotenv_values),
            default=3600,
        ),
        task_projection_max_events=_parse_int(
            _read_env("HEYGENT_TASK_PROJECTION_MAX_EVENTS", 200, dotenv_values),
            default=200,
        ),
        task_execution_queue_enabled=_parse_bool(
            _read_env("HEYGENT_TASK_EXECUTION_QUEUE_ENABLED", "false", dotenv_values),
            default=False,
        ),
        task_execution_worker_count=_parse_int(
            _read_env("HEYGENT_TASK_EXECUTION_WORKER_COUNT", 2, dotenv_values),
            default=2,
        ),
        task_execution_lease_seconds=_parse_int(
            _read_env("HEYGENT_TASK_EXECUTION_LEASE_SECONDS", 300, dotenv_values),
            default=300,
        ),
        task_execution_poll_interval_seconds=_parse_float(
            _read_env("HEYGENT_TASK_EXECUTION_POLL_INTERVAL_SECONDS", 0.5, dotenv_values),
            default=0.5,
        ),
        public_session_limit_per_user=_parse_int(
            _read_env("HEYGENT_PUBLIC_SESSION_LIMIT_PER_USER", 10, dotenv_values),
            default=10,
        ),
        agent_model_request_timeout_seconds=_parse_float(
            _read_env("HEYGENT_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS", 300.0, dotenv_values),
            default=300.0,
        ),
        agent_model_stream_timeout_seconds=_parse_float(
            _read_env("HEYGENT_AGENT_MODEL_STREAM_TIMEOUT_SECONDS", 300.0, dotenv_values),
            default=300.0,
        ),
        agent_loop_default_max_iterations=_parse_int(
            _read_env("HEYGENT_AGENT_LOOP_DEFAULT_MAX_ITERATIONS", 90, dotenv_values),
            default=90,
        ),
        agent_loop_worker_default_max_iterations=_parse_int(
            _read_env("HEYGENT_AGENT_LOOP_WORKER_DEFAULT_MAX_ITERATIONS", 80, dotenv_values),
            default=80,
        ),
        agent_loop_max_iterations=_parse_int(
            _read_env("HEYGENT_AGENT_LOOP_MAX_ITERATIONS", 120, dotenv_values),
            default=120,
        ),
        work_execution_max_iterations=_parse_int(
            _read_env("HEYGENT_WORK_EXECUTION_MAX_ITERATIONS", 24, dotenv_values),
            default=24,
        ),
        agent_secret_encryption_key=_read_env("HEYGENT_AGENT_SECRET_ENCRYPTION_KEY", None, dotenv_values),
        bridge_token=_read_env("HEYGENT_BRIDGE_TOKEN", None, dotenv_values),
    )
