from __future__ import annotations

from app.core.config import get_settings


def test_backend_auth_verify_defaults_to_local_backend(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HEYGENT_BACKEND_BASE_URL", raising=False)
    monkeypatch.delenv("HEYGENT_BACKEND_AUTH_VERIFY_URL", raising=False)
    monkeypatch.delenv("HEYGENT_BACKEND_MEMORY_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("HEYGENT_MEMORY_RECALL_LLM_PLANNER_ENABLED", raising=False)
    monkeypatch.delenv("HEYGENT_INTERNAL_SERVICE_TOKEN", raising=False)

    settings = get_settings()

    assert settings.backend_base_url == "http://127.0.0.1:8080"
    assert settings.backend_auth_verify_url == "http://127.0.0.1:8080/internal/ai/auth/validate"
    assert settings.backend_memory_timeout_seconds == 5.0
    assert settings.backend_tool_timeout_seconds == 10.0
    assert settings.memory_recall_llm_planner_enabled is True
    assert settings.internal_service_token is None


def test_backend_auth_verify_settings_read_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HEYGENT_BACKEND_BASE_URL", "http://backend")
    monkeypatch.setenv("HEYGENT_BACKEND_AUTH_VERIFY_URL", "http://backend/internal/ai/auth/validate")
    monkeypatch.setenv("HEYGENT_BACKEND_MEMORY_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("HEYGENT_BACKEND_TOOL_TIMEOUT_SECONDS", "8.5")
    monkeypatch.setenv("HEYGENT_MEMORY_RECALL_LLM_PLANNER_ENABLED", "false")
    monkeypatch.setenv("HEYGENT_INTERNAL_SERVICE_TOKEN", "service-token")

    settings = get_settings()

    assert settings.backend_base_url == "http://backend"
    assert settings.backend_auth_verify_url == "http://backend/internal/ai/auth/validate"
    assert settings.backend_memory_timeout_seconds == 2.5
    assert settings.backend_tool_timeout_seconds == 8.5
    assert settings.memory_recall_llm_planner_enabled is False
    assert settings.internal_service_token == "service-token"


def test_redis_connection_registry_settings_read_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HEYGENT_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("HEYGENT_WS_CONNECTION_TTL_SECONDS", "120")
    monkeypatch.setenv("HEYGENT_WS_AUTH_RATE_LIMIT_MAX_FAILURES", "3")
    monkeypatch.setenv("HEYGENT_WS_AUTH_RATE_LIMIT_WINDOW_SECONDS", "30")
    monkeypatch.setenv("HEYGENT_TASK_PROJECTION_TTL_SECONDS", "1800")
    monkeypatch.setenv("HEYGENT_TASK_PROJECTION_MAX_EVENTS", "50")

    settings = get_settings()

    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.ws_connection_ttl_seconds == 120
    assert settings.ws_auth_rate_limit_max_failures == 3
    assert settings.ws_auth_rate_limit_window_seconds == 30
    assert settings.task_projection_ttl_seconds == 1800
    assert settings.task_projection_max_events == 50


def test_postgres_settings_read_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HEYGENT_POSTGRES_DSN", "postgresql://user:pass@localhost:5432/heygent")
    monkeypatch.setenv("HEYGENT_POSTGRES_MIGRATIONS_ENABLED", "false")

    settings = get_settings()

    assert settings.postgres_dsn == "postgresql://user:pass@localhost:5432/heygent"
    assert settings.postgres_migrations_enabled is False


def test_cors_settings_read_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HEYGENT_CORS_ALLOWED_ORIGINS", "http://localhost:5173, https://app.example.com")
    monkeypatch.setenv("HEYGENT_CORS_ALLOWED_METHODS", "GET,POST,OPTIONS")
    monkeypatch.setenv("HEYGENT_CORS_ALLOWED_HEADERS", "Authorization,Content-Type,X-Workspace-Key")
    monkeypatch.setenv("HEYGENT_CORS_ALLOW_CREDENTIALS", "false")
    monkeypatch.setenv("HEYGENT_CORS_MAX_AGE_SECONDS", "1200")

    settings = get_settings()

    assert settings.cors_allowed_origins == ["http://localhost:5173", "https://app.example.com"]
    assert settings.cors_allowed_methods == ["GET", "POST", "OPTIONS"]
    assert settings.cors_allowed_headers == ["Authorization", "Content-Type", "X-Workspace-Key"]
    assert settings.cors_allow_credentials is False
    assert settings.cors_max_age_seconds == 1200


def test_cors_settings_default_methods_include_write_methods(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HEYGENT_CORS_ALLOWED_METHODS", raising=False)

    settings = get_settings()

    assert settings.cors_allowed_methods == ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def test_agent_loop_timeout_defaults_are_tolerant(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("HEYGENT_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("HEYGENT_AGENT_MODEL_STREAM_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("HEYGENT_AGENT_LOOP_DEFAULT_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("HEYGENT_AGENT_LOOP_WORKER_DEFAULT_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("HEYGENT_AGENT_LOOP_MAX_ITERATIONS", raising=False)
    monkeypatch.delenv("HEYGENT_WORK_EXECUTION_MAX_ITERATIONS", raising=False)

    settings = get_settings()

    assert settings.agent_model_request_timeout_seconds == 300.0
    assert settings.agent_model_stream_timeout_seconds == 300.0
    assert settings.agent_loop_default_max_iterations == 90
    assert settings.agent_loop_worker_default_max_iterations == 80
    assert settings.agent_loop_max_iterations == 120
    assert settings.work_execution_max_iterations == 24


def test_agent_loop_timeout_settings_read_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HEYGENT_AGENT_MODEL_REQUEST_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("HEYGENT_AGENT_MODEL_STREAM_TIMEOUT_SECONDS", "450")
    monkeypatch.setenv("HEYGENT_AGENT_LOOP_DEFAULT_MAX_ITERATIONS", "70")
    monkeypatch.setenv("HEYGENT_AGENT_LOOP_WORKER_DEFAULT_MAX_ITERATIONS", "75")
    monkeypatch.setenv("HEYGENT_AGENT_LOOP_MAX_ITERATIONS", "140")
    monkeypatch.setenv("HEYGENT_WORK_EXECUTION_MAX_ITERATIONS", "18")

    settings = get_settings()

    assert settings.agent_model_request_timeout_seconds == 600.0
    assert settings.agent_model_stream_timeout_seconds == 450.0
    assert settings.agent_loop_default_max_iterations == 70
    assert settings.agent_loop_worker_default_max_iterations == 75
    assert settings.agent_loop_max_iterations == 140
    assert settings.work_execution_max_iterations == 18
