from typing import TYPE_CHECKING, Any, ClassVar, Self

from django.utils.dateparse import parse_datetime
from queryish import VirtualModel

from wagtail_sharepoint.constants import PK_SEPARATOR
from wagtail_sharepoint.models.queryset import SharepointBaseQuerySet


if TYPE_CHECKING:
    from wagtail_sharepoint.client import Site


__all__ = ["SharepointPage"]


class SharepointPageQuerySet(SharepointBaseQuerySet):
    model: "SharepointPage"

    def fetch_api_response(
        self, query_string: str, offset: int, size: int
    ) -> tuple[list[dict[str, Any]], int, bool]:
        return self._client.search_pages(query_string, offset, size)

    def fetch_item(self, container_id: str, item_id: str):
        return self._client.get_page(container_id, item_id)


class SharepointPage(VirtualModel):
    base_query_class = SharepointPageQuerySet
    id: str = ""
    title: str = ""

    class Meta:
        fields: ClassVar[list[str]] = [
            "id",
            "url",
            "title",
            "site_id",
            "site_name",
            "created_at",
            "last_modified",
        ]
        filter_fields: ClassVar[list[str]] = ["id"]
        verbose_name = "SharePoint page"
        verbose_name_plural = "SharePoint pages"

    @classmethod
    def from_api_data(cls, data: dict, site: "Site | None" = None) -> Self | None:
        if not data:
            return None

        site_id = data.get("parentReference", {}).get("siteId", "")
        return cls(
            id=f"{site_id}{PK_SEPARATOR}{data['id']}",
            title=data.get("title", "") or data.get("fields", {}).get("title", ""),
            url=data.get("webUrl", ""),
            item_id=data["id"],
            site_id=site_id,
            site_name=site.name if site else "",
            created_at=parse_datetime(data.get("createdDateTime", "")),
            last_modified=parse_datetime(data.get("lastModifiedDateTime", "")),
        )

    @classmethod
    def from_query_data(cls, data) -> Self | None:
        return cls.from_api_data(data)

    from_individual_data = from_query_data

    def __str__(self) -> str:
        return self.title or self.id
