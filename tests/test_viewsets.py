import responses

from django.test import TestCase, override_settings
from django.urls import reverse
from wagtail.test.utils import WagtailTestUtils

from wagtail_sharepoint.models import SharepointDocument, SharepointPage
from wagtail_sharepoint.viewsets import (
    sharepoint_document_chooser_viewset,
    sharepoint_page_chooser_viewset,
)

from .utils import (
    DRIVE_ID,
    EXTRA_DRIVE_ID,
    EXTRA_SITE_ID,
    EXTRA_SITE_URL,
    MULTI_SITE_SETTINGS,
    TEST_SITE_ID,
    TEST_SITE_URL,
    get_document_data,
    get_page_data,
    mock_drive_item_response,
    mock_page_response,
    mock_search_response,
    mock_sites_response,
    mock_token_response,
    search_bodies,
)


class ChooserTestMixin(WagtailTestUtils):
    viewset = None

    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = cls.create_test_user()
        cls.chooser_url = cls.viewset.widget_class().get_chooser_modal_url()
        cls.chooser_results_url = reverse(cls.viewset.get_url_name("choose_results"))

    def setUp(self) -> None:
        responses.start()
        self.addCleanup(responses.stop)
        self.addCleanup(responses.reset)

        self.client.force_login(self.user)
        mock_token_response()
        mock_sites_response()

    def get_modal_soup(self, params=None):
        response = self.client.get(self.chooser_url, params or {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["step"], "choose")
        return self.get_soup(response.json()["html"])

    def get_results_soup(self, params=None):
        response = self.client.get(self.chooser_results_url, params or {})
        self.assertEqual(response.status_code, 200)
        return self.get_soup(response.content)

    @staticmethod
    def column_headings(soup) -> list[str]:
        return [th.get_text(strip=True) for th in soup.select("table th")]

    @staticmethod
    def row_titles(soup) -> list[str]:
        return [
            cell.get_text(strip=True) for cell in soup.select("table tbody td.title")
        ]

    def get_query_string(self) -> str:
        return search_bodies()[-1]["requests"][0]["query"]["queryString"]


class DocumentChooseViewTestCase(ChooserTestMixin, TestCase):
    viewset = sharepoint_document_chooser_viewset

    def test_requires_admin_access(self):
        self.client.logout()
        response = self.client.get(self.chooser_url)
        self.assertEqual(response.status_code, 302)

    def test_with_single_site(self):
        mock_search_response([get_document_data("1", "Annual report.pdf")])

        soup = self.get_modal_soup()

        # test no Site column or filter present
        self.assertEqual(
            self.column_headings(soup), ["Title", "Size", "Created", "Last modified"]
        )
        self.assertIsNotNone(soup.select_one("input[name=q]"))
        self.assertIsNone(soup.select_one("select[name=site]"))
        self.assertEqual(self.row_titles(soup), ["Annual report.pdf"])
        self.assertIn("2.0\xa0KB", soup.get_text())
        self.assertEqual(
            self.get_query_string(), f'(path:"{TEST_SITE_URL}") AND isDocument=true'
        )

    def test_search(self):
        mock_search_response([get_document_data()])

        response = self.client.get(self.chooser_results_url, {"q": "  annual  "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.get_query_string(),
            f'annual AND (path:"{TEST_SITE_URL}") AND isDocument=true',
        )
        self.assertTrue(response.context["is_searching"])
        self.assertEqual(response.context["search_query"], "annual")

    def test_no_results(self):
        mock_search_response([])

        soup = self.get_results_soup({"q": "nothing"})

        self.assertEqual(self.row_titles(soup), [])

    def test_pagination(self):
        docs = [get_document_data(str(i), f"doc-{i}.pdf") for i in range(20)]
        mock_search_response(docs, total=45, more=True)

        response = self.client.get(self.chooser_results_url, {"p": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(search_bodies()[-1]["requests"][0]["from"], 20)
        self.assertEqual(response.context["results"].paginator.num_pages, 3)

    def test_chosen(self):
        doc = get_document_data()
        mock_drive_item_response(doc)

        response = self.client.get(
            reverse(
                self.viewset.get_url_name("chosen"), args=[f"{DRIVE_ID}::{doc['id']}"]
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["step"], "chosen")
        self.assertEqual(
            response.json()["result"],
            {
                "id": f"{DRIVE_ID}::{doc['id']}",
                "title": "Annual report.pdf",
                # The widget's edit link opens the file in SharePoint
                "edit_url": doc["webUrl"],
            },
        )

    def test_chosen__not_found(self):
        mock_drive_item_response({"id": "gone"}, DRIVE_ID, status=404)

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            response = self.client.get(
                reverse(self.viewset.get_url_name("chosen"), args=[f"{DRIVE_ID}::gone"])
            )

        self.assertEqual(response.status_code, 404)

    def test_chosen_multiple(self):
        first = get_document_data("1", "a.pdf")
        second = get_document_data("2", "b.pdf")
        mock_drive_item_response(first)
        mock_drive_item_response(second)

        response = self.client.get(
            reverse(self.viewset.get_url_name("chosen_multiple")),
            {"id": [f"{DRIVE_ID}::1", f"{DRIVE_ID}::2"]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted((r["title"], r["edit_url"]) for r in response.json()["result"]),
            [("a.pdf", first["webUrl"]), ("b.pdf", second["webUrl"])],
        )

    def test_widget_value_data(self):
        doc = SharepointDocument.from_api_data(get_document_data())

        self.assertEqual(
            self.viewset.widget_class().get_value_data_from_instance(doc),
            {"id": doc.pk, "edit_url": doc.url, "title": "Annual report.pdf"},
        )

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_with_multiple_sites(self):
        mock_search_response(
            [
                get_document_data("1", "Annual report.pdf"),
                get_document_data(
                    "2",
                    "Leave policy.docx",
                    drive_id=EXTRA_DRIVE_ID,
                    site_url=EXTRA_SITE_URL,
                ),
            ]
        )

        soup = self.get_modal_soup()

        # test Site column and filter present
        self.assertEqual(
            self.column_headings(soup),
            ["Title", "Size", "Site", "Created", "Last modified"],
        )
        options = [
            (option["value"], option.get_text(strip=True))
            for option in soup.select("select[name=site] option")
        ]
        self.assertEqual(
            options,
            [
                ("", "All sites"),
                (TEST_SITE_ID, "Test site"),
                (EXTRA_SITE_ID, "Extra site"),
            ],
        )
        rows = [
            [td.get_text(strip=True) for td in tr.select("td")]
            for tr in soup.select("table tbody tr")
        ]
        self.assertEqual([row[2] for row in rows], ["Test site", "Extra site"])
        self.assertEqual(
            self.get_query_string(),
            f'(path:"{TEST_SITE_URL}" OR path:"{EXTRA_SITE_URL}") AND isDocument=true',
        )

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_with_multiple_sites_filter_by_site(self):
        mock_search_response(
            [
                get_document_data(
                    "2",
                    "Leave policy.docx",
                    drive_id=EXTRA_DRIVE_ID,
                    site_url=EXTRA_SITE_URL,
                )
            ]
        )

        soup = self.get_results_soup({"site": EXTRA_SITE_ID, "q": "leave"})

        self.assertEqual(self.row_titles(soup), ["Leave policy.docx"])
        self.assertEqual(
            self.get_query_string(),
            f'leave AND (path:"{EXTRA_SITE_URL}") AND isDocument=true',
        )

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_filter_by_unknown_site_is_ignored(self):
        mock_search_response([get_document_data()])

        # Invalid choice -> form invalid -> unfiltered listing, not an error
        self.get_results_soup({"site": "not-a-site"})

        self.assertIn(f'path:"{EXTRA_SITE_URL}"', self.get_query_string())


class PageChooseViewTestCase(ChooserTestMixin, TestCase):
    viewset = sharepoint_page_chooser_viewset

    def test_with_single_site(self):
        mock_search_response([get_page_data("p1", "Welcome")])

        soup = self.get_modal_soup()

        # test no Site column or filter present
        self.assertEqual(
            self.column_headings(soup), ["Title", "Created", "Last modified"]
        )
        self.assertIsNone(soup.select_one("select[name=site]"))
        self.assertEqual(self.row_titles(soup), ["Welcome"])
        self.assertEqual(
            self.get_query_string(),
            f'(path:"{TEST_SITE_URL}") AND contentclass:STS_ListItem_WebPageLibrary',
        )

    def test_chosen(self):
        page = get_page_data()
        mock_page_response(page)

        pk = f"{TEST_SITE_ID}::{page['id']}"

        response = self.client.get(
            reverse(
                self.viewset.get_url_name("chosen"),
                args=[pk],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["result"],
            {
                "id": pk,
                "title": "Welcome",
                "edit_url": page["webUrl"],
            },
        )

    def test_chosen__not_found(self):
        mock_page_response({"id": "gone"}, TEST_SITE_ID, status=404)

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            response = self.client.get(
                reverse(
                    self.viewset.get_url_name("chosen"), args=[f"{TEST_SITE_ID}::gone"]
                )
            )

        self.assertEqual(response.status_code, 404)

    def test_widget_value_data(self):
        page = SharepointPage.from_api_data(get_page_data())

        self.assertEqual(
            self.viewset.widget_class().get_value_data_from_instance(page),
            {"id": page.pk, "edit_url": page.url, "title": "Welcome"},
        )

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_with_multiple_sites(self):
        mock_search_response(
            [
                get_page_data("p1", "Welcome"),
                get_page_data(
                    "p2", "Benefits", site_id=EXTRA_SITE_ID, site_url=EXTRA_SITE_URL
                ),
            ]
        )

        soup = self.get_modal_soup()

        # test Site column and filter present
        self.assertEqual(
            self.column_headings(soup), ["Title", "Site", "Created", "Last modified"]
        )
        self.assertEqual(
            [o["value"] for o in soup.select("select[name=site] option")],
            ["", TEST_SITE_ID, EXTRA_SITE_ID],
        )
        self.assertEqual(self.row_titles(soup), ["Welcome", "Benefits"])

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_with_multiple_sites_filter_by_site(self):
        mock_search_response(
            [
                get_page_data(
                    "p2", "Benefits", site_id=EXTRA_SITE_ID, site_url=EXTRA_SITE_URL
                )
            ]
        )

        soup = self.get_results_soup({"site": EXTRA_SITE_ID})

        self.assertEqual(self.row_titles(soup), ["Benefits"])
        self.assertEqual(
            self.get_query_string(),
            f'(path:"{EXTRA_SITE_URL}") AND contentclass:STS_ListItem_WebPageLibrary',
        )
