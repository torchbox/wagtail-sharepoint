import hashlib
import logging

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Self

import requests

from django.core.cache import cache

from .constants import (
    DOCUMENT_FIELDS,
    DOCUMENT_SEARCH_FIELDS,
    PAGE_FIELDS,
    PAGE_SEARCH_FIELDS,
    SHORT_CACHE_TTL,
    SITES_CACHE_TTL,
)


if TYPE_CHECKING:
    from .config import Settings

logger = logging.getLogger(__name__)


class MsGraphApiError(Exception):
    pass


@dataclass(frozen=True)
class Site:
    id: str
    name: str
    url: str

    @property
    def scope_url(self) -> str:
        # Trailing slash so /sites/hr doesn't also match /sites/hr-archive
        return self.url.rstrip("/") + "/"

    def contains(self, url: str) -> bool:
        return bool(url) and url.lower().startswith(self.scope_url.lower())

    @classmethod
    def from_graph(cls, data: dict) -> Self:
        return cls(
            id=data["id"],
            name=data["name"],
            url=data["webUrl"],
        )


def match_site(sites: list[Site], url: str | None) -> Site | None:
    """
    The configured site a URL belongs to. Uses the longest match, so a file in
    /sites/hr resolves to that site even if the tenant root is also configured.
    """
    if not url:
        return None

    matches: list[Site] = [site for site in sites if url and site.contains(url)]
    if not matches:
        return None

    return max(matches, key=lambda site: len(site.scope_url))


class MsGraphApiClient:
    timeout: int = 10

    def __init__(self, config: "Settings"):
        self.config = config
        self.session = requests.Session()

    def _cache_key(self, *parts: str) -> str:
        raw = "|".join(
            [
                self.config.tenant_id,
                self.config.client_id,
                *self.config.site_ids,
                *parts,
            ]
        )
        return "wagtail_sharepoint:" + hashlib.sha256(raw.encode()).hexdigest()

    def get_token(self) -> str:
        """
        @see https://learn.microsoft.com/en-us/graph/auth-v2-user?tabs=http#step-2-request-an-access-token
        :return: The access token
        """
        key = self._cache_key("token")
        if token := cache.get(key):
            return token

        response = self.session.post(
            self.config.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=self.timeout,
        )
        if not response.ok:
            raise MsGraphApiError(
                f"Token request failed ({response.status_code}): {response.text[:500]}"
            )

        payload = response.json()
        # Refresh a few minutes early to avoid using a token as it expires
        ttl = max(int(payload.get("expires_in", 3600)) - 300, 60)
        cache.set(key, payload["access_token"], ttl)
        return payload["access_token"]

    def request(self, method: str, path: str, **kwargs) -> dict | None:
        url = path if path.startswith("https://") else self.config.api_root + path
        headers = {
            "Authorization": f"Bearer {self.get_token()}",
            "Accept": "application/json",
        }
        response = self.session.request(
            method, url, headers=headers, timeout=self.timeout, **kwargs
        )

        if not response.ok:
            logger.error(
                "Graph %s %s -> %s: %s",
                method,
                url,
                response.status_code,
                response.text[:500],
            )
            return None
        return response.json()

    def get_sites(self) -> list[Site]:
        """
        Resolve the configured site ids to Site objects, in configured order.
        Cached, since they rarely change.
        """
        key = self._cache_key("sites", *self.config.site_ids)
        if self.config.cache_enabled and (sites := cache.get(key)) is not None:
            return sites

        data = self.request(
            "GET",
            "/sites/getAllSites",
            params={"$filter": "isPersonalSite ne true", "$orderBy": "createdDateTime"},
        )

        if data is None:
            return []

        sites_by_id = {}
        site_by_collection_id = {}
        site_by_uid = {}
        try:
            for site in data["value"]:
                sites_by_id[site["id"]] = site

                try:
                    parts = site["id"].split(",")
                    site_by_collection_id[parts[1]] = site
                    site_by_uid[parts[2]] = site
                except IndexError:
                    ...
        except KeyError:
            ...

        sites_dict = {}
        for site_id in self.config.site_ids:
            if site_id in sites_by_id:
                site = Site.from_graph(sites_by_id[site_id])
                sites_dict[site.id] = site
            elif site_id in site_by_uid:
                site = Site.from_graph(site_by_uid[site_id])
                sites_dict[site.id] = site
            elif site_id in site_by_collection_id:
                site = Site.from_graph(site_by_collection_id[site_id])
                sites_dict[site.id] = site

        sites = list(sites_dict.values())
        cache.set(key, sites, SITES_CACHE_TTL)

        return sites

    def get_drive_item(self, drive_id: str, item_id: str) -> dict | None:
        """
        Fetches a Sharepoint / OneDrive item given the item and the drive id.

        @see https://learn.microsoft.com/en-us/graph/api/driveitem-get?view=graph-rest-1.0&tabs=http
        @see https://learn.microsoft.com/en-us/graph/query-parameters?tabs=http#select
        """
        cache_key = self._cache_key("item", item_id)
        if self.config.cache_enabled and (item := cache.get(cache_key)) is not None:
            return item

        item = self.request(
            "GET",
            f"/drives/{drive_id}/items/{item_id}",
            params={"$select": DOCUMENT_FIELDS},
        )
        cache.set(cache_key, item, SHORT_CACHE_TTL)
        return item

    def get_page(self, site_id: str, item_id: str) -> dict | None:
        """
        Fetches a page with the given id and site id.

        @see https://learn.microsoft.com/en-us/graph/api/sitepage-get?view=graph-rest-1.0&tabs=http
        @see https://learn.microsoft.com/en-us/graph/query-parameters?tabs=http#select
        """
        cache_key = self._cache_key("page", item_id)
        if self.config.cache_enabled and (item := cache.get(cache_key)) is not None:
            return item

        item = self.request(
            "GET",
            f"/sites/{site_id}/pages/{item_id}/microsoft.graph.sitePage",
            params={"$select": PAGE_FIELDS},
        )
        cache.set(cache_key, item, SHORT_CACHE_TTL)
        return item

    def search_documents(
        self,
        query_string: str,
        offset: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """
        Searches documents.

        :return: tuple (resources, total, more_results_available).
        """

        cache_key = self._cache_key("documents", query_string, str(offset), str(size))
        if self.config.cache_enabled and (data := cache.get(cache_key)) is not None:
            return data

        body = {
            "requests": [
                {
                    "entityTypes": ["driveItem"],
                    "query": {"queryString": f"{query_string} AND isDocument=true"},
                    "from": offset,
                    "size": size,
                    "region": self.config.search_region,
                    "fields": DOCUMENT_SEARCH_FIELDS,
                }
            ]
        }
        data = self.request("POST", "/search/query", json=body) or {}
        try:
            container = data["value"][0]["hitsContainers"][0]
        except (KeyError, IndexError):
            return [], 0, False

        resources = [hit["resource"] for hit in container.get("hits") or []]
        data = (
            resources,
            container.get("total", 0),
            container.get("moreResultsAvailable", False),
        )
        cache.set(cache_key, data, SHORT_CACHE_TTL)
        return data

    def search_pages(
        self,
        query_string: str,
        offset: int,
        size: int,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        """
        Searches pages

        :return: tuple (resources, total, more_results_available).
        """

        cache_key = self._cache_key("pages", query_string, str(offset), str(size))
        if self.config.cache_enabled and (data := cache.get(cache_key)) is not None:
            return data

        body = {
            "requests": [
                {
                    "entityTypes": ["listItem"],
                    "query": {
                        "queryString": f"{query_string} AND contentclass:STS_ListItem_WebPageLibrary"
                    },
                    "fields": PAGE_SEARCH_FIELDS,
                    "from": offset,
                    "size": size,
                    "region": self.config.search_region,
                    "sortProperties": [
                        {"name": "createdDateTime", "isDescending": False}
                    ],
                }
            ]
        }
        data = self.request("POST", "/search/query", json=body) or {}
        try:
            container = data["value"][0]["hitsContainers"][0]
            resources = [hit["resource"] for hit in container.get("hits") or []]
            data = (
                resources,
                container.get("total", 0),
                container.get("moreResultsAvailable", False),
            )
        except (KeyError, IndexError):
            data = [], 0, False

        cache.set(cache_key, data, SHORT_CACHE_TTL)
        return data


@lru_cache
def get_client() -> MsGraphApiClient:
    from .config import conf

    return MsGraphApiClient(conf)
