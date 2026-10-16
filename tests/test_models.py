from datetime import UTC, datetime

from django.test import SimpleTestCase

from wagtail_sharepoint.client import Site
from wagtail_sharepoint.models import SharepointDocument, SharepointPage

from .utils import (
    DRIVE_ID,
    TEST_SITE_ID,
    TEST_SITE_URL,
    get_document_data,
    get_page_data,
)


SITE = Site(id=TEST_SITE_ID, name="Intranet", url=TEST_SITE_URL)


class TestSharepointDocument(SimpleTestCase):
    def test_from_api_data(self):
        doc = SharepointDocument.from_api_data(get_document_data(), SITE)

        self.assertEqual(doc.id, f"{DRIVE_ID}::01DOC0001")
        self.assertEqual(doc.pk, doc.id)
        self.assertEqual(doc.item_id, "01DOC0001")
        self.assertEqual(doc.drive_id, DRIVE_ID)
        self.assertEqual(doc.name, "Annual report.pdf")
        self.assertEqual(doc.url, f"{TEST_SITE_URL}/Shared Documents/Annual report.pdf")
        self.assertEqual(doc.site_id, TEST_SITE_ID)
        self.assertEqual(doc.site_name, "Intranet")
        self.assertEqual(doc.mime_type, "application/pdf")
        self.assertEqual(doc.size, 2048)
        self.assertEqual(doc.created_at, datetime(2026, 1, 11, 9, 30, tzinfo=UTC))
        self.assertEqual(doc.last_modified, datetime(2026, 2, 20, 16, 45, tzinfo=UTC))

    def test_from_api_data__minimal_payload(self):
        # Search hits can omit most fields; only "id" is required
        doc = SharepointDocument.from_api_data({"id": "X1", "file": None})

        self.assertEqual(doc.id, "::X1")
        self.assertEqual(doc.drive_id, "")
        self.assertEqual(doc.name, "")
        self.assertEqual(doc.url, "")
        self.assertEqual(doc.mime_type, "")
        self.assertEqual(doc.site_id, "")
        self.assertEqual(doc.site_name, "")
        self.assertIsNone(doc.size)
        self.assertIsNone(doc.created_at)
        self.assertIsNone(doc.last_modified)

    def test_from_api_data__requires_id(self):
        with self.assertRaises(KeyError):
            SharepointDocument.from_api_data({"name": "a.pdf"})

    def test_from_query_data(self):
        doc = SharepointDocument.from_query_data(get_document_data())

        self.assertIsInstance(doc, SharepointDocument)
        self.assertEqual(doc.id, f"{DRIVE_ID}::01DOC0001")
        # No site context when built from raw query data
        self.assertEqual(doc.site_id, "")
        self.assertEqual(doc.site_name, "")

    def test_from_individual_data(self):
        doc = SharepointDocument.from_individual_data(get_document_data())

        self.assertEqual(doc, SharepointDocument.from_query_data(get_document_data()))
        self.assertEqual(doc.name, "Annual report.pdf")

    def test_str(self):
        self.assertEqual(
            str(SharepointDocument.from_api_data(get_document_data())),
            "Annual report.pdf",
        )
        self.assertEqual(str(SharepointDocument.from_api_data({"id": "X1"})), "::X1")

    def test_extension(self):
        cases = {
            "report.pdf": "pdf",
            "Budget.XLSX": "xlsx",
            "archive.tar.gz": "gz",
            "README": "",
            "": "",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                doc = SharepointDocument(id="x", name=name)
                self.assertEqual(doc.extension, expected)

    def test_size_human(self):
        cases = {
            0: "0\xa0bytes",
            512: "512\xa0bytes",
            2048: "2.0\xa0KB",
            5 * 1024 * 1024: "5.0\xa0MB",
            None: "0\xa0bytes",
        }
        for size, expected in cases.items():
            with self.subTest(size=size):
                self.assertEqual(
                    SharepointDocument(id="x", size=size).size_human, expected
                )


class TestSharepointPage(SimpleTestCase):
    def test_from_api_data(self):
        page = SharepointPage.from_api_data(get_page_data(), SITE)

        self.assertEqual(page.id, f"{TEST_SITE_ID}::0a1b2c3d-page-0001")
        self.assertEqual(page.pk, page.id)
        self.assertEqual(page.title, "Welcome")
        self.assertEqual(page.url, f"{TEST_SITE_URL}/SitePages/Welcome.aspx")
        self.assertEqual(page.site_id, TEST_SITE_ID)
        self.assertEqual(page.site_name, "Intranet")
        self.assertEqual(page.created_at, datetime(2025, 3, 1, 8, 0, tzinfo=UTC))
        self.assertEqual(page.last_modified, datetime(2025, 3, 5, 12, 15, tzinfo=UTC))

    def test_from_api_data__site_id_comes_from_parent_reference(self):
        # Unlike documents, the page's site_id is read from the payload and the
        # Site object only supplies the display name.
        other = Site(id="other", name="Other", url=TEST_SITE_URL)
        page = SharepointPage.from_api_data(get_page_data(), other)

        self.assertEqual(page.site_id, TEST_SITE_ID)
        self.assertEqual(page.site_name, "Other")

    def test_from_api_data__title_falls_back_to_list_item_fields(self):
        # listItem search hits carry the title under "fields"
        data = get_page_data(title="")
        data["fields"] = {"title": "From fields"}

        self.assertEqual(SharepointPage.from_api_data(data).title, "From fields")

    def test_from_api_data__empty(self):
        self.assertIsNone(SharepointPage.from_api_data({}))
        self.assertIsNone(SharepointPage.from_api_data(None))

    def test_from_query_data(self):
        page = SharepointPage.from_query_data(get_page_data())

        self.assertIsInstance(page, SharepointPage)
        self.assertEqual(page.title, "Welcome")
        self.assertEqual(page.site_name, "")

    def test_from_individual_data(self):
        page = SharepointPage.from_individual_data(get_page_data())

        self.assertEqual(page, SharepointPage.from_query_data(get_page_data()))
        self.assertIsNone(SharepointPage.from_individual_data({}))

    def test_str(self):
        self.assertEqual(str(SharepointPage.from_api_data(get_page_data())), "Welcome")

        untitled = get_page_data(title="")
        untitled.pop("fields", None)
        self.assertEqual(
            str(SharepointPage.from_api_data(untitled)),
            f"{TEST_SITE_ID}::0a1b2c3d-page-0001",
        )
