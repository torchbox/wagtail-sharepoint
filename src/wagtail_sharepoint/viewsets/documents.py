from django import forms
from django.http import Http404
from django.utils.translation import gettext_lazy as _
from wagtail.admin.forms.choosers import BaseFilterForm
from wagtail.admin.ui.tables import Column, DateColumn
from wagtail.admin.views.generic.chooser import (
    BaseChooseView,
    ChooseResultsView,
    ChooseView,
    ChosenMultipleView,
    ChosenView,
)
from wagtail.admin.viewsets.chooser import ChooserViewSet
from wagtail.admin.widgets import BaseChooser

from wagtail_sharepoint.client import get_client
from wagtail_sharepoint.models import SharepointDocument


__all__ = ["sharepoint_document_chooser_viewset"]


class SharepointDocumentFilterForm(BaseFilterForm):
    q = forms.CharField(
        label=_("Search term"),
        widget=forms.TextInput(attrs={"placeholder": _("Search documents")}),
        required=False,
    )

    def __init__(self, *args, sites=(), **kwargs):
        super().__init__(*args, **kwargs)
        if len(sites) > 1:
            self.fields["site"] = forms.ChoiceField(
                label=_("Site"),
                choices=[
                    ("", _("All sites")),
                    *[(site.id, site.name) for site in sites],
                ],
                required=False,
                widget=forms.Select(attrs={"data-chooser-modal-search-filter": True}),
            )

    def filter(self, objects):
        objects = super().filter(objects)

        if search_query := self.cleaned_data.get("q", "").strip():
            objects = objects.filter(q=search_query)
            self.is_searching = True
            self.search_query = search_query

        if site := self.cleaned_data.get("site"):
            objects = objects.filter(site=site)

        return objects


class SharepointChooseViewMixin(BaseChooseView):
    filter_form_class = SharepointDocumentFilterForm

    def get_filter_form(self):
        return self.filter_form_class(self.request.GET, sites=get_client().get_sites())

    @property
    def columns(self):
        if len(get_client().get_sites()) > 1:
            site_column = [Column("site_name", label=_("Site"), sort_key=None)]
        else:
            site_column = []

        return [
            *super().columns,
            Column("size", label=_("Size"), accessor="size_human"),
            *site_column,
            DateColumn("created_at", label=_("Created"), sort_key=None),
            DateColumn("last_modified", label=_("Last modified"), sort_key=None),
        ]

    class Meta:
        abstract = True


class SharepointDocumentChooseView(SharepointChooseViewMixin, ChooseView):
    pass


class SharepointDocumentChooseResultsView(SharepointChooseViewMixin, ChooseResultsView):
    pass


class SharepointChosenView(ChosenView):
    def get_object(self, pk):
        try:
            return super().get_object(pk)
        except SharepointDocument.DoesNotExist as e:
            raise Http404 from e

    def get_edit_item_url(self, instance):
        # The widget's "edit" button opens the document in SharePoint
        return instance.url


class SharepointDocumentChosenMultipleView(ChosenMultipleView):
    def get_edit_item_url(self, instance):
        # The widget's "edit" button opens the document in SharePoint
        return instance.url


class SharePointDocumentChooserWidget(BaseChooser):
    def get_value_data_from_instance(self, instance):
        return {
            "id": instance.pk,
            "edit_url": instance.url,
            self.display_title_key: self.get_display_title(instance),
        }


class SharepointDocumentChooserViewSet(ChooserViewSet):
    model = SharepointDocument
    icon = "sharepoint"
    choose_one_text = _("Choose a SharePoint document")
    choose_another_text = _("Choose another document")
    edit_item_text = _("Open in SharePoint")
    per_page = 20

    # There's no ForeignKey to register a form field override for
    register_widget = False

    base_widget_class = SharePointDocumentChooserWidget
    choose_view_class = SharepointDocumentChooseView
    choose_results_view_class = SharepointDocumentChooseResultsView
    chosen_view_class = SharepointChosenView
    chosen_multiple_view_class = SharepointDocumentChosenMultipleView


sharepoint_document_chooser_viewset = SharepointDocumentChooserViewSet(
    "sharepoint_document_chooser",
    url_prefix="sharepoint-documents",
)
