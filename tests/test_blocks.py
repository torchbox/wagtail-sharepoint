import responses

from django.test import TestCase
from testapp.models import TestPage
from wagtail.blocks import StreamValue
from wagtail.models import Site
from wagtail.test.utils import WagtailTestUtils

from wagtail_sharepoint.blocks import (
    SharepointDocumentChooserBlock,
    SharepointPageChooserBlock,
    VirtualPkField,
)
from wagtail_sharepoint.models import SharepointDocument, SharepointPage

from .utils import (
    API_ROOT,
    DRIVE_ID,
    TEST_SITE_ID,
    get_document_data,
    get_page_data,
    mock_drive_item_response,
    mock_page_response,
    mock_sites_response,
    mock_token_response,
)


@responses.activate
class BlockTestCase(WagtailTestUtils, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = Site.objects.get(is_default_site=True).root_page
        cls.doc_data = get_document_data("1", "a.pdf")
        cls.other_doc_data = get_document_data("2", "b.pdf")
        cls.page_data = get_page_data()
        cls.doc_pk = f"{DRIVE_ID}::1"
        cls.other_doc_pk = f"{DRIVE_ID}::2"
        cls.page_pk = f"{TEST_SITE_ID}::{cls.page_data['id']}"

    def setUp(self):
        mock_token_response()
        mock_sites_response()
        self.document_block = SharepointDocumentChooserBlock()
        self.page_block = SharepointPageChooserBlock()

    def test_model_class(self):
        self.assertIs(self.document_block.model_class, SharepointDocument)
        self.assertIs(self.page_block.model_class, SharepointPage)

    def test_deconstruct_uses_public_path(self):
        # Migrations must reference the block by its importable path
        path, _args, _kwargs = self.document_block.deconstruct()
        self.assertEqual(
            path, "wagtail_sharepoint.blocks.SharepointDocumentChooserBlock"
        )
        path, _args, _kwargs = self.page_block.deconstruct()
        self.assertEqual(path, "wagtail_sharepoint.blocks.SharepointPageChooserBlock")

    def test_pk_field(self):
        for block in (self.document_block, self.page_block):
            with self.subTest(block=block):
                self.assertIsInstance(block.pk_field, VirtualPkField)
                # pks are opaque strings; must not be coerced (e.g. to int)
                self.assertEqual(block.pk_field.to_python(self.doc_pk), self.doc_pk)

    def test_get_prep_value(self):
        doc = SharepointDocument.from_api_data(self.doc_data)
        page = SharepointPage.from_api_data(self.page_data)

        self.assertEqual(self.document_block.get_prep_value(doc), self.doc_pk)
        self.assertEqual(self.page_block.get_prep_value(page), self.page_pk)
        self.assertIsNone(self.document_block.get_prep_value(None))

    def test_document_to_python(self):
        mock_drive_item_response(self.doc_data)

        value = self.document_block.to_python(self.doc_pk)

        self.assertIsInstance(value, SharepointDocument)
        self.assertEqual(value.pk, self.doc_pk)
        self.assertEqual(value.site_name, "Intranet")
        self.assertIsNone(self.document_block.to_python(None))

    def test_document_to_python__missing_item(self):
        responses.get(f"{API_ROOT}/drives/{DRIVE_ID}/items/gone", status=404)

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            self.assertIsNone(self.document_block.to_python(f"{DRIVE_ID}::gone"))

    def test_page_to_python(self):
        mock_page_response(self.page_data)

        value = self.page_block.to_python(self.page_pk)

        self.assertIsInstance(value, SharepointPage)
        self.assertEqual(value.title, "Welcome")

    def test_bulk_to_python(self):
        first = mock_drive_item_response(self.doc_data)
        mock_drive_item_response(self.other_doc_data)

        values = self.document_block.bulk_to_python(
            [self.doc_pk, None, self.other_doc_pk, self.doc_pk]
        )

        # Order and gaps preserved; repeated ids become separate instances
        self.assertEqual(
            [v.pk if v else None for v in values],
            [self.doc_pk, None, self.other_doc_pk, self.doc_pk],
        )
        self.assertIsNot(values[0], values[3])
        # in_bulk dedupes the lookup
        self.assertEqual(first.call_count, 1)

    def test_value_from_form(self):
        mock_drive_item_response(self.doc_data)
        doc = SharepointDocument.from_api_data(self.doc_data)

        self.assertIs(self.document_block.value_from_form(doc), doc)
        self.assertEqual(
            self.document_block.value_from_form(self.doc_pk).pk, self.doc_pk
        )

    def test_streamfield_round_trip(self):
        mock_drive_item_response(self.doc_data)
        mock_page_response(self.page_data)
        page = self.root.add_child(
            instance=TestPage(
                title="Test",
                slug="test",
                body=[
                    (
                        "sharepoint_document",
                        SharepointDocument.from_api_data(self.doc_data),
                    ),
                    ("sharepoint_page", SharepointPage.from_api_data(self.page_data)),
                ],
            )
        )

        stored = TestPage.objects.get(pk=page.pk)
        self.assertEqual(
            [(b["type"], b["value"]) for b in stored.body.raw_data],
            [("sharepoint_document", self.doc_pk), ("sharepoint_page", self.page_pk)],
        )
        self.assertIsInstance(stored.body, StreamValue)
        doc_value, page_value = (child.value for child in stored.body)
        self.assertEqual(doc_value.name, "a.pdf")
        self.assertEqual(page_value.title, "Welcome")

    def test_render_page(self):
        mock_drive_item_response(self.doc_data)
        page = self.root.add_child(
            instance=TestPage(
                title="Test",
                slug="test",
                body=[
                    (
                        "sharepoint_document",
                        SharepointDocument.from_api_data(self.doc_data),
                    )
                ],
            )
        )

        response = self.client.get(page.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "a.pdf")

    def test_page_editor_renders_chosen_values(self):
        mock_drive_item_response(self.doc_data)
        page = self.root.add_child(
            instance=TestPage(
                title="Test",
                slug="test",
                body=[
                    (
                        "sharepoint_document",
                        SharepointDocument.from_api_data(self.doc_data),
                    )
                ],
            )
        )
        self.login()

        response = self.client.get(f"/admin/pages/{page.pk}/edit/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.doc_data["webUrl"])
