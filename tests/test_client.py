import json
import unittest

from unittest import mock

import responses

from django.core.cache import cache
from django.test import TestCase, override_settings
from responses import matchers
from wagtail.test.utils import WagtailTestUtils

from wagtail_sharepoint.client import (
    MsGraphApiClient,
    MsGraphApiError,
    Site,
    get_client,
    match_site,
)
from wagtail_sharepoint.config import conf
from wagtail_sharepoint.constants import (
    DOCUMENT_FIELDS,
    DOCUMENT_SEARCH_FIELDS,
    PAGE_FIELDS,
    PAGE_SEARCH_FIELDS,
    SHORT_CACHE_TTL,
    SITES_CACHE_TTL,
)

from .utils import (
    API_ROOT,
    BASE_SETTINGS,
    DRIVE_ID,
    EXTRA_SITE,
    EXTRA_SITE_ID,
    EXTRA_SITE_UID,
    EXTRA_SITE_URL,
    MULTI_SITE_SETTINGS,
    SEARCH_URL,
    SITES_URL,
    TEST_SITE,
    TEST_SITE_ID,
    TEST_SITE_UID,
    TEST_SITE_URL,
    TOKEN,
    TOKEN_URL,
    bearer_matcher,
    get_document_data,
    get_page_data,
    mock_drive_item_response,
    mock_page_response,
    mock_search_response,
    mock_sites_response,
    mock_token_response,
)


CACHE_DISABLED = override_settings(
    DEBUG=True, WAGTAIL_SHAREPOINT={**MULTI_SITE_SETTINGS, "DISABLE_CACHE": True}
)


class SiteTestCase(TestCase):
    def test_from_graph(self):
        site = Site.from_graph(
            {"id": "123", "name": "Test", "webUrl": EXTRA_SITE_URL, "extra": 1}
        )
        self.assertEqual(site, Site(id="123", name="Test", url=EXTRA_SITE_URL))

    def test_scope_url_has_a_single_trailing_slash(self):
        self.assertEqual(
            Site("123", "Test", EXTRA_SITE_URL).scope_url, EXTRA_SITE_URL + "/"
        )
        self.assertEqual(
            Site("123", "Test", EXTRA_SITE_URL + "/").scope_url, EXTRA_SITE_URL + "/"
        )

    def test_contains(self):
        site = Site("x", "EXTRA_SITE", EXTRA_SITE_URL)
        self.assertTrue(site.contains(EXTRA_SITE_URL + "/Shared Documents/a.pdf"))
        self.assertTrue(site.contains(EXTRA_SITE_URL.upper() + "/DOC.PDF"))
        # Sibling site sharing a prefix must not match
        self.assertFalse(site.contains(EXTRA_SITE_URL + "-archive/a.pdf"))
        self.assertFalse(site.contains(""))
        self.assertFalse(site.contains(None))

    def test_match_site_uses_longest_match(self):
        root = Site("root", "Root", "https://contoso.sharepoint.com")
        hr = Site("hr", "EXTRA_SITE", EXTRA_SITE_URL)
        sites = [root, hr]

        self.assertEqual(match_site(sites, EXTRA_SITE_URL + "/test_doc.pdf"), hr)
        self.assertEqual(match_site(sites, TEST_SITE_URL + "/test_doc.pdf"), root)
        self.assertIsNone(match_site(sites, "https://elsewhere.example.com/x"))
        self.assertIsNone(match_site(sites, None))
        self.assertIsNone(match_site([], EXTRA_SITE_URL + "/test_doc.pdf"))


@responses.activate
class ClientTestCase(WagtailTestUtils, TestCase):
    def setUp(self):
        super().setUp()
        self.token_mock = mock_token_response()

        self.api_client = MsGraphApiClient(conf)

    def test_get_client_is_cached(self):
        self.assertIs(get_client(), get_client())
        self.assertIs(get_client().config, conf)

    def test_cache_key(self):
        key = self.api_client._cache_key("item", "123")

        self.assertTrue(key.startswith("wagtail_sharepoint:"))
        # sha256 hex digest keeps keys memcached-safe whatever the input
        self.assertEqual(len(key.removeprefix("wagtail_sharepoint:")), 64)
        self.assertEqual(key, self.api_client._cache_key("item", "123"))
        self.assertNotEqual(key, self.api_client._cache_key("item", "456"))
        self.assertNotEqual(key, self.api_client._cache_key("page", "123"))

    def test_cache_key_varies_with_configuration(self):
        key = self.api_client._cache_key("token")

        for override in (
            {"TENANT_ID": "other_tenant"},
            {"CLIENT_ID": "other_client"},
            {"SITE_ID": "other-site"},
        ):
            with (
                self.subTest(override=override),
                override_settings(
                    WAGTAIL_SHAREPOINT={
                        **BASE_SETTINGS,
                        "SITE_ID": TEST_SITE_UID,
                        **override,
                    }
                ),
            ):
                self.assertNotEqual(self.api_client._cache_key("token"), key)

    def test_request(self):
        responses.get(
            f"{API_ROOT}/me",
            json={"ok": True},
            match=[
                bearer_matcher(),
                matchers.header_matcher({"Accept": "application/json"}),
                matchers.query_param_matcher({"a": "1"}),
            ],
        )

        self.assertEqual(
            self.api_client.request("GET", "/me", params={"a": "1"}), {"ok": True}
        )

    def test_request_with_absolute_url(self):
        full_url = f"{API_ROOT}/sites"
        responses.get(full_url, json={"value": []})

        self.assertEqual(self.api_client.request("GET", full_url), {"value": []})
        self.assertEqual(responses.calls[-1].request.url, full_url)

    def test_request_logs_error_if_bad_response(self):
        responses.get(f"{API_ROOT}/me", status=403, body="Access denied " * 100)

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR") as logs:
            self.assertIsNone(self.api_client.request("GET", "/me"))

        self.assertEqual(len(logs.records), 1)
        message = logs.records[0].getMessage()
        self.assertIn(f"Graph GET {API_ROOT}/me -> 403", message)
        # The body is truncated so a large error page doesn't flood the logs
        self.assertLess(len(message), 600)

    def test_get_token(self):
        self.assertEqual(self.api_client.get_token(), TOKEN)
        # A second call is served from the cache
        self.assertEqual(self.api_client.get_token(), TOKEN)
        self.assertEqual(self.token_mock.call_count, 1)
        self.assertEqual(cache.get(self.api_client._cache_key("token")), TOKEN)

    def test_get_token__ttl(self):
        cases = [
            (3600, 3300),  # refreshed five minutes early
            (100, 60),  # never cached for less than a minute
            (None, 3300),  # expires_in missing -> assume an hour
        ]
        for expires_in, expected_ttl in cases:
            with self.subTest(expires_in=expires_in):
                responses.reset()
                payload = {"access_token": TOKEN}
                if expires_in is not None:
                    payload["expires_in"] = expires_in
                responses.post(TOKEN_URL, json=payload)

                with mock.patch("wagtail_sharepoint.client.cache") as mock_cache:
                    mock_cache.get.return_value = None
                    self.api_client.get_token()

                mock_cache.set.assert_called_once_with(
                    self.api_client._cache_key("token"), TOKEN, expected_ttl
                )

    def test_get_token__error(self):
        responses.reset()
        responses.post(TOKEN_URL, status=401, json={"error": "invalid_client"})

        with self.assertRaisesMessage(MsGraphApiError, "Token request failed (401)"):
            self.api_client.get_token()

        self.assertIsNone(cache.get(self.api_client._cache_key("token")))

    def test_get_token__error_propagates_from_request(self):
        responses.reset()
        responses.post(TOKEN_URL, status=500)

        with self.assertRaises(MsGraphApiError):
            self.api_client.request("GET", "/me")

    def test_get_sites(self):
        sites_mock = mock_sites_response(
            match=[
                bearer_matcher(),
                matchers.query_param_matcher(
                    {
                        "$filter": "isPersonalSite ne true",
                        "$orderBy": "createdDateTime",
                    }
                ),
            ]
        )

        sites = self.api_client.get_sites()

        self.assertEqual(
            sites, [Site(id=TEST_SITE_ID, name="Intranet", url=TEST_SITE_URL)]
        )
        self.assertEqual(sites_mock.call_count, 1)

    @override_settings(
        WAGTAIL_SHAREPOINT={
            **BASE_SETTINGS,
            # Configured order wins over Graph's order; the duplicate
            # (same site by two ids) is collapsed.
            "SITE_IDS": [EXTRA_SITE_UID, TEST_SITE_UID, EXTRA_SITE_ID],
        }
    )
    def test_get_sites__keeps_configured_order_and_dedupes(self):
        mock_sites_response()

        self.assertEqual(
            [site.id for site in self.api_client.get_sites()],
            [EXTRA_SITE_ID, TEST_SITE_ID],
        )

    def test_get_sites__from_cache(self):
        sites_mock = mock_sites_response()

        first = self.api_client.get_sites()
        second = self.api_client.get_sites()

        self.assertEqual(first, second)
        self.assertEqual(sites_mock.call_count, 1)

    def test_get_sites__cache_ttl(self):
        mock_sites_response()

        with mock.patch.object(cache, "set", wraps=cache.set) as cache_set:
            self.api_client.get_sites()

        cache_set.assert_any_call(
            self.api_client._cache_key("sites", TEST_SITE_UID),
            mock.ANY,
            SITES_CACHE_TTL,
        )

    @CACHE_DISABLED
    def test_get_sites__with_cache_disabled(self):
        sites_mock = mock_sites_response()

        self.api_client.get_sites()
        self.api_client.get_sites()

        self.assertEqual(sites_mock.call_count, 2)

    @override_settings(
        WAGTAIL_SHAREPOINT={
            **BASE_SETTINGS,
            "SITE_IDS": ["does-not-exist", EXTRA_SITE_UID],
        }
    )
    def test_get_sites__with_a_bad_site_id(self):
        mock_sites_response(
            [
                *[TEST_SITE, EXTRA_SITE],
                # Malformed ids must not break resolution of the others
                {"id": "no-commas", "name": "Odd", "webUrl": f"{TEST_SITE_URL}/odd"},
            ]
        )

        self.assertEqual(
            self.api_client.get_sites(),
            [Site(id=EXTRA_SITE_ID, name="EXTRA_SITE", url=EXTRA_SITE_URL)],
        )

    def test_get_sites__with_unexpected_payload(self):
        responses.get(SITES_URL, json={"unexpected": []})

        self.assertEqual(self.api_client.get_sites(), [])

    def test_get_sites__request_failure_is_not_cached(self):
        responses.get(SITES_URL, status=503)
        ok = mock_sites_response()

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            self.assertEqual(self.api_client.get_sites(), [])

        # the error is not cached, so the next call is good
        self.assertEqual(len(self.api_client.get_sites()), 1)
        self.assertEqual(ok.call_count, 1)

    def test_get_drive_item(self):
        item = get_document_data()
        item_mock = mock_drive_item_response(
            item,
            match=[
                bearer_matcher(),
                matchers.query_param_matcher({"$select": DOCUMENT_FIELDS}),
            ],
        )

        self.assertEqual(self.api_client.get_drive_item(DRIVE_ID, item["id"]), item)
        self.assertEqual(item_mock.call_count, 1)

    def test_get_drive_item__not_found(self):
        responses.get(f"{API_ROOT}/drives/{DRIVE_ID}/items/missing", status=404)

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            self.assertIsNone(self.api_client.get_drive_item(DRIVE_ID, "missing"))

    def test_get_drive_item__from_cache(self):
        item = get_document_data()
        item_mock = mock_drive_item_response(item)

        with mock.patch.object(cache, "set", wraps=cache.set) as cache_set:
            self.api_client.get_drive_item(DRIVE_ID, item["id"])
        self.assertEqual(self.api_client.get_drive_item(DRIVE_ID, item["id"]), item)

        self.assertEqual(item_mock.call_count, 1)
        cache_set.assert_any_call(
            self.api_client._cache_key("item", item["id"]), item, SHORT_CACHE_TTL
        )

    @CACHE_DISABLED
    def test_get_drive_item__with_cache_disabled(self):
        item = get_document_data()
        item_mock = mock_drive_item_response(item)

        self.api_client.get_drive_item(DRIVE_ID, item["id"])
        self.api_client.get_drive_item(DRIVE_ID, item["id"])

        self.assertEqual(item_mock.call_count, 2)

    def test_get_page(self):
        page = get_page_data()
        page_mock = mock_page_response(
            page,
            match=[
                bearer_matcher(),
                matchers.query_param_matcher({"$select": PAGE_FIELDS}),
            ],
        )

        self.assertEqual(self.api_client.get_page(TEST_SITE_ID, page["id"]), page)
        self.assertEqual(page_mock.call_count, 1)

    def test_get_page__from_cache(self):
        page = get_page_data()
        page_mock = mock_page_response(page)

        self.api_client.get_page(TEST_SITE_ID, page["id"])
        self.assertEqual(self.api_client.get_page(TEST_SITE_ID, page["id"]), page)

        self.assertEqual(page_mock.call_count, 1)

    @CACHE_DISABLED
    def test_get_page__with_cache_disabled(self):
        page = get_page_data()
        page_mock = mock_page_response(page)

        self.api_client.get_page(TEST_SITE_ID, page["id"])
        self.api_client.get_page(TEST_SITE_ID, page["id"])

        self.assertEqual(page_mock.call_count, 2)

    def test_search_documents(self):
        docs = [get_document_data("1", "a.pdf"), get_document_data("2", "b.docx")]
        search_mock = mock_search_response(
            docs,
            total=42,
            more=True,
            match=[
                bearer_matcher(),
                matchers.json_params_matcher(
                    {
                        "requests": [
                            {
                                "entityTypes": ["driveItem"],
                                "query": {"queryString": "budget AND isDocument=true"},
                                "from": 20,
                                "size": 10,
                                "region": "GBR",
                                "fields": DOCUMENT_SEARCH_FIELDS,
                            }
                        ]
                    }
                ),
            ],
        )

        self.assertEqual(
            self.api_client.search_documents("budget", 20, 10), (docs, 42, True)
        )
        # Same arguments -> cached
        self.api_client.search_documents("budget", 20, 10)
        self.assertEqual(search_mock.call_count, 1)

    def test_search_documents__cache_varies_by_arguments(self):
        search_mock = mock_search_response([get_document_data()])

        self.api_client.search_documents("budget", 0, 20)
        self.api_client.search_documents("budget", 20, 20)
        self.api_client.search_documents("budget", 0, 10)
        self.api_client.search_documents("minutes", 0, 20)

        self.assertEqual(search_mock.call_count, 4)

    @CACHE_DISABLED
    def test_search_documents__with_cache_disabled(self):
        search_mock = mock_search_response([get_document_data()])

        self.api_client.search_documents("budget", 0, 20)
        self.api_client.search_documents("budget", 0, 20)

        self.assertEqual(search_mock.call_count, 2)

    def test_search_documents__with_no_hits(self):
        responses.post(SEARCH_URL, json={"value": [{"hitsContainers": [{"total": 0}]}]})

        self.assertEqual(
            self.api_client.search_documents("nothing", 0, 20), ([], 0, False)
        )

    def test_search_documents__error_is_not_cached(self):
        responses.post(SEARCH_URL, status=500)
        ok = mock_search_response([get_document_data()])

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            self.assertEqual(
                self.api_client.search_documents("q", 0, 20), ([], 0, False)
            )

        resources, total, _ = self.api_client.search_documents("q", 0, 20)
        self.assertEqual((len(resources), total), (1, 1))
        self.assertEqual(ok.call_count, 1)

    def test_search_documents__unexpected_payload(self):
        for payload in ({}, {"value": []}, {"value": [{"hitsContainers": []}]}):
            with self.subTest(payload=payload):
                cache.clear()
                responses.reset()
                mock_token_response()
                responses.post(SEARCH_URL, json=payload)
                self.assertEqual(
                    self.api_client.search_documents("q", 0, 20), ([], 0, False)
                )

    def test_search_pages(self):
        pages = [get_page_data("p1", "Welcome"), get_page_data("p2", "Benefits")]
        search_mock = mock_search_response(
            pages,
            total=2,
            match=[
                bearer_matcher(),
                matchers.json_params_matcher(
                    {
                        "requests": [
                            {
                                "entityTypes": ["listItem"],
                                "query": {
                                    "queryString": "welcome AND contentclass:STS_ListItem_WebPageLibrary"
                                },
                                "fields": PAGE_SEARCH_FIELDS,
                                "from": 0,
                                "size": 20,
                                "region": "GBR",
                                "sortProperties": [
                                    {"name": "createdDateTime", "isDescending": False}
                                ],
                            }
                        ]
                    }
                ),
            ],
        )

        self.assertEqual(
            self.api_client.search_pages("welcome", 0, 20), (pages, 2, False)
        )
        self.api_client.search_pages("welcome", 0, 20)
        self.assertEqual(search_mock.call_count, 1)

    @override_settings(
        WAGTAIL_SHAREPOINT={**MULTI_SITE_SETTINGS, "SEARCH_REGION": "NAM"}
    )
    def test_search_uses_configured_region(self):
        mock_search_response()

        self.api_client.search_documents("q", 0, 20)
        self.api_client.search_pages("q", 0, 20)

        regions = [
            json.loads(call.request.body)["requests"][0]["region"]
            for call in responses.calls
            if call.request.url == SEARCH_URL
        ]
        self.assertEqual(regions, ["NAM", "NAM"])

    def test_search_pages__unexpected_payload(self):
        responses.post(SEARCH_URL, json={"value": []})

        self.assertEqual(self.api_client.search_pages("q", 0, 20), ([], 0, False))

    @unittest.expectedFailure
    def test_search_pages__error_is_not_cached(self):
        # search_pages caches the empty fallback for SHORT_CACHE_TTL, unlike
        # search_documents, so a transient Graph error hides every page from
        # the chooser for five minutes.
        responses.post(SEARCH_URL, status=500)
        ok = mock_search_response([get_page_data()])

        with self.assertLogs("wagtail_sharepoint.client", level="ERROR"):
            self.assertEqual(self.api_client.search_pages("q", 0, 20), ([], 0, False))

        resources, _total, _more = self.api_client.search_pages("q", 0, 20)
        self.assertEqual(len(resources), 1)
        self.assertEqual(ok.call_count, 1)
