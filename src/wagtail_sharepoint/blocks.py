from django.utils.functional import cached_property

from .viewsets import (
    sharepoint_document_chooser_viewset,
    sharepoint_page_chooser_viewset,
)


__all__ = ["SharepointDocumentChooserBlock", "SharepointPageChooserBlock"]


class VirtualPkField:
    def to_python(self, value: str) -> str:
        return value


class VirtualModelMixin:
    @cached_property
    def pk_field(self):
        # Fake pk field for FieldBloc.bulk_to_python which does
        # self.pk_field.to_python(value)
        return VirtualPkField()


SharepointDocumentChooserBlockBase = (
    sharepoint_document_chooser_viewset.get_block_class(
        name="SharepointDocumentChooserBlock", module_path="wagtail_sharepoint.blocks"
    )
)


class SharepointDocumentChooserBlock(
    VirtualModelMixin, SharepointDocumentChooserBlockBase
):
    class Meta:
        template = "wagtail_sharepoint/sharepoint_document.html"


SharepointPageChooserBlockBase = sharepoint_page_chooser_viewset.get_block_class(
    name="SharepointPageChooserBlock", module_path="wagtail_sharepoint.blocks"
)


class SharepointPageChooserBlock(VirtualModelMixin, SharepointPageChooserBlockBase):
    class Meta:
        template = "wagtail_sharepoint/sharepoint_page.html"
