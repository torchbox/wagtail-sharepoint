from collections.abc import Iterable
from functools import cached_property
from typing import TYPE_CHECKING, Any

from queryish import Queryish

from wagtail_sharepoint.client import get_client, match_site
from wagtail_sharepoint.constants import PK_SEPARATOR


if TYPE_CHECKING:
    from queryish import VirtualModel

    from wagtail_sharepoint.client import MsGraphApiClient, Site

__all__ = ["SharepointBaseQuerySet"]

PK_FILTERS: set[str] = {"pk", "id"}
PK_IN_FILTERS: set[str] = {"pk__in", "id__in"}
VALID_FILTERS: set[str] = PK_FILTERS | PK_IN_FILTERS | {"q", "site"}


class SharepointBaseQuerySet(Queryish):
    model: "VirtualModel | None" = (
        None  # note; VirtualObject sets this via VirtualModelMetaclass
    )
    max_page_size = 20

    @cached_property
    def _client(self) -> "MsGraphApiClient":
        return get_client()

    @cached_property
    def _sites(self):
        return self._client.get_sites()

    @property
    def ordered(self) -> bool:
        # MS Graph Search returns results in a stable relevance order.
        # Returning True to stop Wagtail forcing order_by("pk") and Django's paginator warning.
        return True

    def all(self):
        return self.clone()

    def filter_is_valid(self, key, val):
        return key in VALID_FILTERS

    def _parse_filters(self) -> tuple[list[str] | None, str, str | None]:
        pks: list[str] | None = None  # None = no pk filter; list = restrict to these
        q = []
        site_id = None
        for key, val in self.filters:
            if key in PK_FILTERS or key in PK_IN_FILTERS:
                values = [str(val)] if key in PK_FILTERS else [str(v) for v in val if v]
                if pks is None:
                    pks = list(dict.fromkeys(values))
                else:
                    pks = [pk for pk in pks if pk in values]
            elif key == "q":
                if val and str(val).strip():
                    q.append(str(val).strip())
            elif key == "site":
                site_id = val

        return pks, " ".join(q), site_id

    def _scoped_sites(self, site_id) -> list["Site"]:
        sites = self._sites
        if site_id:
            sites = [site for site in sites if site.id == site_id]

        return sites

    @staticmethod
    def _build_query_string(query_string: str, sites: list["Site"]) -> str:
        # Drop sites nested inside another configured site: the outer path
        # already covers them and a shorter KQL query is cheaper.
        scope = " OR ".join(f'path:"{site.url}"' for site in sites)
        return f"{query_string} AND ({scope})" if query_string else f"({scope})"

    def _slice(self, items):
        stop = None if self.limit is None else self.offset + self.limit
        return items[self.offset : stop]

    def _fetch_by_pk(self, pk: str, sites: list["Site"]) -> "VirtualModel | None":
        try:
            container_id, item_id = pk.split(PK_SEPARATOR)
        except ValueError:
            return None

        item = self.fetch_item(container_id, item_id)
        if not item or "folder" in item:
            return None

        # Only return items from the configured (sub)sites, even if the app
        # registration can see more than that.
        if (site := match_site(sites, item.get("webUrl"))) is None:
            return None

        return self.model.from_api_data(item, site)  # ty: ignore[unresolved-attribute]

    def _fetch_many_by_pk(self, pks, site_id) -> list["VirtualModel"]:
        sites = self._scoped_sites(site_id)
        docs = []
        for pk in pks:
            doc = self._fetch_by_pk(pk, sites)
            if doc is not None:
                docs.append(doc)
        return docs

    def fetch_api_response(
        self, query_string: str, offset: int, size: int
    ) -> tuple[list[dict[str, Any]], int, bool]:
        raise NotImplementedError

    def fetch_item(self, container_id: str, item_id: str):
        raise NotImplementedError

    def run_query(self) -> Iterable["VirtualModel"]:
        pks, q, site_id = self._parse_filters()
        if pks is not None:
            # pk lookups (chosen view, widget rendering, ChooserBlock) use the
            # drive item endpoint directly. They don't need the search index.
            yield from self._slice(self._fetch_many_by_pk(pks, site_id))
            return

        if not (sites := self._scoped_sites(site_id)):
            return

        query_string = self._build_query_string(q, sites)

        size = (
            self.max_page_size
            if self.limit is None
            else min(self.limit, self.max_page_size)
        )
        resources, _total, _more = self.fetch_api_response(
            query_string, self.offset, size
        )

        for resource in resources:
            site = match_site(sites, resource.get("webUrl"))
            yield self.model.from_api_data(resource, site)  # ty: ignore[unresolved-attribute]

    def run_count(self) -> int:
        pks, q, site_id = self._parse_filters()
        if pks is not None:
            return len(self._slice(self._fetch_many_by_pk(pks, site_id)))

        if not (sites := self._scoped_sites(site_id)):
            return 0

        # `run_count` is called by the Django paginator before `run_query` so
        # the following is same as getting the first chunk via `run_query` as
        # the results are cached for a short time, so avoids duplicate API queries.
        _resources, total, _more = self.fetch_api_response(
            self._build_query_string(q, sites), 0, self.max_page_size
        )
        # total is the full result set; adjust it to the slice
        # (offset first, then cap at limit)
        count = max(0, total - self.offset)
        if self.limit is not None:
            count = min(count, self.limit)
        return count

    def in_bulk(
        self, id_list: list | None = None, field_name: str = "pk"
    ) -> dict[str, "VirtualModel"]:
        # Used by ChooserBlock.bulk_to_python when rendering StreamFields
        ids = [str(pk) for pk in (id_list or []) if pk]
        if not ids:
            return {}
        return {doc.pk: doc for doc in self.filter(pk__in=ids)}
