from typing import TYPE_CHECKING

from wagtail import hooks

from .viewsets import (
    sharepoint_document_chooser_viewset,
    sharepoint_page_chooser_viewset,
)


if TYPE_CHECKING:
    from wagtail.admin.viewsets.chooser import ChooserViewSet


@hooks.register("register_admin_viewset")
def register_sharepoint_document_chooser_viewset() -> "ChooserViewSet":
    return sharepoint_document_chooser_viewset


@hooks.register("register_admin_viewset")
def register_sharepoint_page_chooser_viewset() -> "ChooserViewSet":
    return sharepoint_page_chooser_viewset


@hooks.register("register_icons")
def register_icons(icons: list[str]) -> list[str]:
    """Registers custom icons.

    Sources:
    - https://service-manual.ons.gov.uk/brand-guidelines/iconography/icon-set
    """
    return [
        *icons,
        "wagtail_sharepoint/icons/sharepoint.svg",
    ]
