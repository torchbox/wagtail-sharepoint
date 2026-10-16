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
from wagtail_sharepoint.models import SharepointPage


__all__ = ["sharepoint_page_chooser_viewset"]


class SharepointPageFilterForm(BaseFilterForm):
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
    filter_form_class = SharepointPageFilterForm

    def get_filter_form(self):
        return self.filter_form_class(self.request.GET, sites=get_client().get_sites())

    @property
    def columns(self) -> list[Column]:
        if len(get_client().get_sites()) > 1:
            site_column = [Column("site_name", label=_("Site"), sort_key=None)]
        else:
            site_column = []

        return [
            *super().columns,
            *site_column,
            DateColumn("created_at", label=_("Created"), sort_key=None),
            DateColumn("last_modified", label=_("Last modified"), sort_key=None),
        ]

    class Meta:
        abstract = True


class SharepointPageChooseView(SharepointChooseViewMixin, ChooseView):
    pass


class SharepointPageChooseResultsView(SharepointChooseViewMixin, ChooseResultsView):
    pass


class SharepointPageChosenView(ChosenView):
    def get_object(self, pk):
        try:
            return super().get_object(pk)
        except SharepointPage.DoesNotExist as e:
            raise Http404 from e

    def get_edit_item_url(self, instance):
        # The widget's "edit" button opens the document in SharePoint
        return instance.url


class SharepointPageChosenMultipleView(ChosenMultipleView):
    def get_edit_item_url(self, instance):
        # The widget's "edit" button opens the document in SharePoint
        return instance.url


class SharePointPageChooserWidget(BaseChooser):
    def get_value_data_from_instance(self, instance):
        return {
            "id": instance.pk,
            "edit_url": instance.url,
            self.display_title_key: self.get_display_title(instance),
        }


class SharepointPageChooserViewSet(ChooserViewSet):
    model = SharepointPage
    icon = "sharepoint"
    choose_one_text = _("Choose a SharePoint page")
    choose_another_text = _("Choose another page")
    edit_item_text = _("Open in SharePoint")
    per_page = 20

    # There's no ForeignKey to register a form field override for
    register_widget = False

    base_widget_class = SharePointPageChooserWidget
    choose_view_class = SharepointPageChooseView
    choose_results_view_class = SharepointPageChooseResultsView
    chosen_view_class = SharepointPageChosenView
    chosen_multiple_view_class = SharepointPageChosenMultipleView


sharepoint_page_chooser_viewset = SharepointPageChooserViewSet(
    "sharepoint_page_chooser",
    url_prefix="sharepoint-pages",
)
