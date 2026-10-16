from unittest import mock

import responses

from django.core.cache import cache
from django.test import TestCase, override_settings

from wagtail_sharepoint.client import Site, get_client
from wagtail_sharepoint.constants import PK_SEPARATOR
from wagtail_sharepoint.models import SharepointDocument, SharepointPage
from wagtail_sharepoint.models.queryset import SharepointBaseQuerySet

from .utils import (
    API_ROOT,
    DRIVE_ID,
    EXTRA_DRIVE_ID,
    EXTRA_SITE_ID,
    EXTRA_SITE_URL,
    MULTI_SITE_SETTINGS,
    SEARCH_URL,
    SITES_URL,
    TEST_SITE_ID,
    TEST_SITE_URL,
    UNUSED_SITE_URL,
    get_document_data,
    get_page_data,
    mock_drive_item_response,
    mock_page_response,
    mock_search_response,
    mock_sites_response,
    mock_token_response,
    search_bodies,
)


TEST_SITE = Site(id=TEST_SITE_ID, name="Test site", url=TEST_SITE_URL)
EXTRA_SITE = Site(id=EXTRA_SITE_ID, name="Extra site", url=EXTRA_SITE_URL)

MISSING_PK = f"{DRIVE_ID}{PK_SEPARATOR}gone"


def pk(data) -> str:
    return f"{data['parentReference']['driveId']}{PK_SEPARATOR}{data['id']}"


class SharepointBaseQuerySetTestCase(TestCase):
    """
    Shared queryset behaviour, exercised through SharepointDocument as the
    concrete subclass. Type-specific wiring (search_documents vs search_pages,
    drive items vs site pages) is covered by the per-model test cases below.
    """

    def setUp(self):
        responses.start()
        self.addCleanup(responses.stop)
        self.addCleanup(responses.reset)

        mock_token_response()
        self.sites_mock = mock_sites_response()
        self.test_doc = get_document_data("1", "a.pdf")
        self.extra_doc = get_document_data(
            "2", "b.pdf", drive_id=EXTRA_DRIVE_ID, site_url=EXTRA_SITE_URL
        )

    def test_client_uses_cached_client(self):
        self.assertIs(SharepointDocument.objects._client, get_client())

    def test_sites_is_cached(self):
        qs = SharepointDocument.objects.filter(q="x")

        with mock.patch.object(
            get_client(), "get_sites", wraps=get_client().get_sites
        ) as get_sites:
            self.assertEqual(qs._sites, [TEST_SITE])
            self.assertEqual(qs._sites, [TEST_SITE])

        get_sites.assert_called_once_with()

    def test_ordered(self):
        self.assertTrue(SharepointDocument.objects.ordered)
        self.assertTrue(SharepointDocument.objects.filter(q="x").ordered)

    def test_invalid_filter(self):
        with self.assertRaisesMessage(ValueError, "Invalid filter field: name"):
            SharepointDocument.objects.filter(name="x")

    def test_parse_filters(self):
        qs = (
            SharepointDocument.objects.filter(pk__in=["a", "b", "c", "a", ""])
            .filter(id__in=["b", "c", "d"])
            .filter(q="  budget ")
            .filter(q="")
            .filter(q="2025")
            .filter(site="site-1")
        )
        self.assertEqual(qs._parse_filters(), (["b", "c"], "budget 2025", "site-1"))
        self.assertEqual(SharepointDocument.objects._parse_filters(), (None, "", None))
        self.assertEqual(
            SharepointDocument.objects.filter(pk="a").filter(id="b")._parse_filters(),
            ([], "", None),
        )

    def test_build_query_string(self):
        build = SharepointBaseQuerySet._build_query_string

        self.assertEqual(
            build("budget", [TEST_SITE]), f'budget AND (path:"{TEST_SITE_URL}")'
        )
        self.assertEqual(build("", [TEST_SITE]), f'(path:"{TEST_SITE_URL}")')
        self.assertEqual(
            build("budget", [TEST_SITE, EXTRA_SITE]),
            f'budget AND (path:"{TEST_SITE_URL}" OR path:"{EXTRA_SITE_URL}")',
        )

    def test_fetch_api_response_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            SharepointBaseQuerySet().fetch_api_response("q", 0, 20)

    def test_fetch_item_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            SharepointBaseQuerySet().fetch_item("drive", "item")

    def test_fetch_by_pk(self):
        item_mock = mock_drive_item_response(self.test_doc)
        qs = SharepointDocument.objects.all()

        with mock.patch.object(
            SharepointDocument,
            "from_api_data",
            wraps=SharepointDocument.from_api_data,
        ) as from_api_data:
            result = qs._fetch_by_pk(pk(self.test_doc), [TEST_SITE])

        self.assertEqual(item_mock.call_count, 1)
        from_api_data.assert_called_once_with(self.test_doc, TEST_SITE)
        self.assertEqual(result.pk, pk(self.test_doc))
        self.assertEqual(result.site_id, TEST_SITE_ID)
        self.assertEqual(result.site_name, "Test site")

    def test_fetch_by_pk__returns_none(self):
        qs = SharepointDocument.objects.all()
        folder = get_document_data("F1", "Folder", folder={"childCount": 3})
        archived = get_document_data("A1", "old.pdf", site_url=UNUSED_SITE_URL)
        mock_drive_item_response(folder)
        mock_drive_item_response(archived)
        responses.get(f"{API_ROOT}/drives/{DRIVE_ID}/items/gone", status=404)

        cases = {
            "malformed pk": "no-separator",
            "too many separators": PK_SEPARATOR.join(["a", "b", "c"]),
            "folder": pk(folder),
            "outside configured sites": pk(archived),
            "not found": MISSING_PK,
        }
        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            for label, value in cases.items():
                with self.subTest(label):
                    self.assertIsNone(qs._fetch_by_pk(value, [TEST_SITE]))

    def test_run_query__calls_fetch_api_response(self):
        search_mock = mock_search_response([self.test_doc, self.extra_doc], total=2)

        results = list(SharepointDocument.objects.filter(q="budget"))

        self.assertEqual(search_mock.call_count, 1)
        request = search_bodies()[0]["requests"][0]
        self.assertEqual(
            request["query"]["queryString"],
            f'budget AND (path:"{TEST_SITE_URL}") AND isDocument=true',
        )
        self.assertEqual((request["from"], request["size"]), (0, 20))
        self.assertEqual(
            [r.pk for r in results], [pk(self.test_doc), pk(self.extra_doc)]
        )
        # Each hit is tagged with the configured site its URL falls under
        self.assertEqual([r.site_id for r in results], [TEST_SITE_ID, ""])
        self.assertEqual([r.site_name for r in results], ["Test site", ""])

    def test_run_query__passes_offset(self):
        mock_search_response([self.test_doc])

        list(SharepointDocument.objects.filter(q="budget")[20:40])

        self.assertEqual(search_bodies()[0]["requests"][0]["from"], 20)

    def test_run_query__without_search_term_scopes_to_sites(self):
        mock_search_response([self.test_doc])

        list(SharepointDocument.objects.filter(q="   "))

        self.assertEqual(
            search_bodies()[0]["requests"][0]["query"]["queryString"],
            f'(path:"{TEST_SITE_URL}") AND isDocument=true',
        )

    def test_run_query__calls_fetch_many_by_pk_if_passed_ids(self):
        other = get_document_data("3", "c.pdf")
        mock_drive_item_response(self.test_doc)
        mock_drive_item_response(other)
        pks = [pk(self.test_doc), pk(other)]

        results = list(SharepointDocument.objects.filter(pk__in=pks))

        self.assertEqual([r.pk for r in results], pks)
        self.assertEqual(search_bodies(), [])

        # Slicing is applied to the fetched items
        sliced = list(SharepointDocument.objects.filter(pk__in=pks)[1:])
        self.assertEqual([r.pk for r in sliced], [pk(other)])

    def test_run_query__pk_lookup_skips_missing_items(self):
        mock_drive_item_response(self.test_doc)
        responses.get(f"{API_ROOT}/drives/{DRIVE_ID}/items/gone", status=404)

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            results = list(
                SharepointDocument.objects.filter(
                    pk__in=[MISSING_PK, pk(self.test_doc)]
                )
            )

        self.assertEqual([r.pk for r in results], [pk(self.test_doc)])

    def test_get(self):
        mock_drive_item_response(self.test_doc)

        self.assertEqual(
            SharepointDocument.objects.get(pk=pk(self.test_doc)).name, "a.pdf"
        )
        with self.assertRaises(SharepointDocument.DoesNotExist):
            SharepointDocument.objects.get(pk="bad")

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_run_query__with_site_filter(self):
        mock_search_response([self.extra_doc])

        results = list(SharepointDocument.objects.filter(q="x", site=EXTRA_SITE_ID))

        self.assertEqual(
            search_bodies()[0]["requests"][0]["query"]["queryString"],
            f'x AND (path:"{EXTRA_SITE_URL}") AND isDocument=true',
        )
        self.assertEqual(results[0].site_id, EXTRA_SITE_ID)

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_run_query__with_site_filter_and_pks(self):
        mock_drive_item_response(self.test_doc)

        # test_doc lives on TEST_SITE, so it is excluded when EXTRA_SITE is selected
        self.assertEqual(
            list(
                SharepointDocument.objects.filter(
                    pk=pk(self.test_doc), site=EXTRA_SITE_ID
                )
            ),
            [],
        )

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_run_query__with_bad_site_filter(self):
        self.assertEqual(
            list(SharepointDocument.objects.filter(q="x", site="nope")), []
        )
        self.assertEqual(search_bodies(), [])

    def test_run_query__with_no_configured_sites(self):
        responses.replace(responses.GET, SITES_URL, json={"value": []})

        self.assertEqual(list(SharepointDocument.objects.filter(q="x")), [])
        self.assertEqual(SharepointDocument.objects.filter(q="x").count(), 0)
        self.assertEqual(search_bodies(), [])

    def test_run_count__calls_fetch_api_response(self):
        search_mock = mock_search_response([self.test_doc], total=42)
        qs = SharepointDocument.objects.filter(q="budget")

        self.assertEqual(qs.count(), 42)
        # Count and the first page share one (cached) search request
        list(qs[:20])
        self.assertEqual(search_mock.call_count, 1)

    def test_run_count__with_offset(self):
        mock_search_response([self.test_doc], total=42)
        qs = SharepointDocument.objects.filter(q="x")

        self.assertEqual(qs[5:].count(), 37)
        self.assertEqual(qs[:10].count(), 10)
        self.assertEqual(qs[50:].count(), 0)

    def test_run_count__with_offset_and_limit(self):
        mock_search_response([self.test_doc], total=42)

        self.assertEqual(SharepointDocument.objects.filter(q="x")[5:15].count(), 10)

    def test_run_count__calls_fetch_many_by_pk_if_passed_ids(self):
        mock_drive_item_response(self.test_doc)
        responses.get(f"{API_ROOT}/drives/{DRIVE_ID}/items/gone", status=404)

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            count = SharepointDocument.objects.filter(
                pk__in=[pk(self.test_doc), MISSING_PK]
            ).count()

        self.assertEqual(count, 1)
        self.assertEqual(search_bodies(), [])

    @override_settings(WAGTAIL_SHAREPOINT=MULTI_SITE_SETTINGS)
    def test_run_count__with_bad_site_filter(self):
        self.assertEqual(SharepointDocument.objects.filter(site="nope").count(), 0)
        self.assertEqual(search_bodies(), [])

    def test_in_bulk(self):
        other = get_document_data("3", "c.pdf")
        mock_drive_item_response(self.test_doc)
        mock_drive_item_response(other)

        result = SharepointDocument.objects.in_bulk(
            [pk(self.test_doc), None, "", pk(other)]
        )

        self.assertEqual(set(result), {pk(self.test_doc), pk(other)})
        self.assertEqual(result[pk(other)].name, "c.pdf")

    def test_in_bulk__empty(self):
        calls_before = len(responses.calls)

        self.assertEqual(SharepointDocument.objects.in_bulk([]), {})
        self.assertEqual(SharepointDocument.objects.in_bulk(None), {})
        self.assertEqual(SharepointDocument.objects.in_bulk([None, ""]), {})
        self.assertEqual(len(responses.calls), calls_before)

    def test_manager_state_is_not_shared_between_requests(self):
        mock_search_response([self.test_doc], total=1)
        self.assertEqual(SharepointDocument.objects.all().count(), 1)

        cache.clear()
        responses.replace(
            responses.POST,
            SEARCH_URL,
            json={"value": [{"hitsContainers": [{"hits": [], "total": 2}]}]},
        )
        self.assertEqual(SharepointDocument.objects.all().count(), 2)


class SharepointDocumentQuerySetTestCase(TestCase):
    def setUp(self):
        responses.start()
        self.addCleanup(responses.stop)
        self.addCleanup(responses.reset)

        mock_token_response()

        self.queryset = SharepointDocument.objects.all()

    def test_fetch_api_response_uses_search_documents(self):
        doc = get_document_data()
        mock_search_response([doc], total=7, more=True)

        self.assertEqual(
            self.queryset.fetch_api_response("budget", 0, 20), ([doc], 7, True)
        )
        self.assertEqual(
            search_bodies()[0]["requests"][0]["entityTypes"], ["driveItem"]
        )

    def test_fetch_item_uses_get_drive_item(self):
        doc = get_document_data()
        item_mock = mock_drive_item_response(doc)

        self.assertEqual(self.queryset.fetch_item(DRIVE_ID, doc["id"]), doc)
        self.assertEqual(item_mock.call_count, 1)

    def test_end_to_end(self):
        mock_sites_response()
        doc = get_document_data()
        mock_search_response([doc])
        mock_drive_item_response(doc)

        [found] = self.queryset.filter(q="annual")
        self.assertIsInstance(found, SharepointDocument)
        self.assertEqual(found.site_name, "Test site")
        self.assertEqual(self.queryset.get(pk=found.pk), found)


class SharepointPageQuerySetTestCase(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.queryset = SharepointPage.objects

    def setUp(self):
        responses.start()
        self.addCleanup(responses.stop)
        self.addCleanup(responses.reset)

        mock_token_response()

    def test_fetch_api_response_uses_search_pages(self):
        page = get_page_data()
        mock_search_response([page], total=1)

        self.assertEqual(
            self.queryset.fetch_api_response("welcome", 0, 20), ([page], 1, False)
        )
        self.assertEqual(search_bodies()[0]["requests"][0]["entityTypes"], ["listItem"])

    def test_fetch_item_uses_get_page(self):
        page = get_page_data()
        page_mock = mock_page_response(page)

        self.assertEqual(self.queryset.fetch_item(TEST_SITE_ID, page["id"]), page)
        self.assertEqual(page_mock.call_count, 1)

    def test_end_to_end(self):
        mock_sites_response()
        page = get_page_data()
        mock_search_response([page])
        mock_page_response(page)

        item = self.queryset.first()
        self.assertIsInstance(item, SharepointPage)
        self.assertEqual(item.site_name, "Test site")
        self.assertEqual(self.queryset.get(pk=item.pk), item)
