from typing import ClassVar

from wagtail.fields import StreamField
from wagtail.models import Page

from wagtail_sharepoint.blocks import (
    SharepointDocumentChooserBlock,
    SharepointPageChooserBlock,
)


class TestPage(Page):
    body = StreamField(
        [
            ("sharepoint_page", SharepointPageChooserBlock()),
            ("sharepoint_document", SharepointDocumentChooserBlock()),
        ]
    )

    content_panels: ClassVar[list] = [*Page.content_panels, "body"]
