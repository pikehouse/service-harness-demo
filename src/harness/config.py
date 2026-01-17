"""Configuration management using Pydantic settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Grafana Cloud - Prometheus
    prometheus_url: str = "https://prometheus-prod-67-prod-us-west-0.grafana.net/api/prom"
    prometheus_username: str = ""
    grafana_api_token: str = ""

    # Grafana Cloud - Loki
    loki_url: str = "https://logs-prod-021.grafana.net"
    loki_username: str = ""

    # Database
    database_url: str = "sqlite:///./harness.db"

    # Claude API
    anthropic_api_key: str = ""

    # Environment
    environment: str = "development"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
