"""환경 설정.

인증은 Entra ID OIDC를 구현하되, 클라이언트 설정이 없으면 개발용 로컬 로그인으로
동작한다 (오픈 이슈 O3 미해결 상태에서도 실행·검증이 가능하도록).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "FRMS"
    #: SQLite 기본. 운영 배포 시 postgresql+psycopg://... 로 바꾸면 그대로 동작한다.
    database_url: str = "sqlite:///./frms.db"
    session_secret: str = "dev-only-secret-change-me"
    timezone_display: str = "Asia/Seoul"

    # --- Entra ID OIDC (설정되면 자동으로 SSO 모드) ---
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    entra_client_secret: str | None = None
    entra_redirect_uri: str = "http://localhost:8000/auth/callback"

    @property
    def sso_enabled(self) -> bool:
        return bool(self.entra_tenant_id and self.entra_client_id and self.entra_client_secret)

    @property
    def oidc_metadata_url(self) -> str:
        return (
            f"https://login.microsoftonline.com/{self.entra_tenant_id}"
            "/v2.0/.well-known/openid-configuration"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
