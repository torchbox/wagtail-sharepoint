from typing import TYPE_CHECKING, Any, ClassVar, Self

from django.template.defaultfilters import filesizeformat
from django.utils.dateparse import parse_datetime
from queryish import VirtualModel

from wagtail_sharepoint.constants import PK_SEPARATOR
from wagtail_sharepoint.models.queryset import SharepointBaseQuerySet


if TYPE_CHECKING:
    from wagtail_sharepoint.client import Site

__all__ = ["SharepointDocument"]


class SharepointDocumentQuerySet(SharepointBaseQuerySet):
    model: "SharepointDocument | None" = (
        None  # note; VirtualObject sets this via VirtualModelMetaclass
    )

    def fetch_api_response(
        self, query_string: str, offset: int, size: int
    ) -> tuple[list[dict[str, Any]], int, bool]:
        return self._client.search_documents(query_string, offset, size)

    def fetch_item(self, container_id: str, item_id: str):
        return self._client.get_drive_item(container_id, item_id)


class SharepointDocument(VirtualModel):
    base_query_class = SharepointDocumentQuerySet
    name: str = ""
    id: str = ""
    size: str = ""

    class Meta:
        fields: ClassVar[list[str]] = [
            "id",
            "name",
            "url",
            "item_id",
            "drive_id",
            "site_id",
            "site_name",
            "mime_type",
            "size",
            "created_at",
            "last_modified",
        ]
        verbose_name = "SharePoint document"
        verbose_name_plural = "SharePoint documents"

    @classmethod
    def from_api_data(cls, data: dict, site: "Site | None" = None) -> Self:
        drive_id = data.get("parentReference", {}).get("driveId", "")
        return cls(
            id=f"{drive_id}{PK_SEPARATOR}{data['id']}",
            name=data.get("name", ""),
            url=data.get("webUrl", ""),
            drive_id=drive_id,
            item_id=data["id"],
            site_id=site.id if site else "",
            site_name=site.name if site else "",
            mime_type=(data.get("file") or {}).get("mimeType", ""),
            size=data.get("size"),
            created_at=parse_datetime(data.get("createdDateTime", "")),
            last_modified=parse_datetime(data.get("lastModifiedDateTime", "")),
        )

    @classmethod
    def from_query_data(cls, data) -> "SharepointDocument":
        return cls.from_api_data(data)

    from_individual_data = from_query_data

    @property
    def extension(self) -> str:
        return self.name.rsplit(".", 1)[-1].lower() if "." in self.name else ""

    @property
    def size_human(self) -> str:
        return filesizeformat(self.size)

    def __str__(self) -> str:
        return self.name or self.id
