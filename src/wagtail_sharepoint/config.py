from django.conf import settings


class Settings:
    api_root: str = "https://graph.microsoft.com/v1.0"

    @property
    def _user_settings(self) -> dict[str, str]:
        user_settings = getattr(settings, "WAGTAIL_SHAREPOINT", None)
        return user_settings if isinstance(user_settings, dict) else {}

    @property
    def tenant_id(self) -> str:
        return self._user_settings["TENANT_ID"]

    @property
    def client_id(self) -> str:
        return self._user_settings["CLIENT_ID"]

    @property
    def client_secret(self) -> str:
        return self._user_settings["CLIENT_SECRET"]

    @property
    def site_ids(self) -> list[str]:
        if site_id := self._user_settings.get("SITE_ID", ""):
            return [site_id]

        return list(self._user_settings.get("SITE_IDS", []))

    @property
    def uses_single_site(self) -> bool:
        return len(self.site_ids) == 1

    @property
    def search_region(self) -> str:
        return self._user_settings.get("SEARCH_REGION", "GBR")

    @property
    def cache_enabled(self) -> bool:
        return not (
            settings.DEBUG and bool(self._user_settings.get("DISABLE_CACHE", False))
        )

    @property
    def token_url(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"


conf = Settings()
