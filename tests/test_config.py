from django.test import SimpleTestCase, override_settings

from wagtail_sharepoint.config import Settings, conf

from .utils import BASE_SETTINGS


class ConfigTest(SimpleTestCase):
    def setUp(self):
        self.settings = Settings()

    def test_module_level_conf(self):
        self.assertIsInstance(conf, Settings)

    def test_api_root(self):
        self.assertEqual(self.settings.api_root, "https://graph.microsoft.com/v1.0")

    def test_tenant_id(self):
        self.assertEqual(self.settings.tenant_id, "test_tenant")

    def test_client_id(self):
        self.assertEqual(self.settings.client_id, "test_client_id")

    def test_client_secret(self):
        self.assertEqual(self.settings.client_secret, "test_not_a_secret")

    @override_settings(WAGTAIL_SHAREPOINT={})
    def test_required_settings_raise_when_missing(self):
        for attr in ("tenant_id", "client_id", "client_secret"):
            with self.subTest(attr=attr), self.assertRaises(KeyError):
                getattr(self.settings, attr)

    @override_settings(WAGTAIL_SHAREPOINT="not-a-dict")
    def test_non_dict_setting_is_ignored(self):
        self.assertEqual(self.settings._user_settings, {})
        self.assertEqual(self.settings.site_ids, [])

    def test_sited_ids__with_single_site(self):
        self.assertEqual(
            self.settings.site_ids, ["aac37637-022b-45e3-9d25-59f7aa14d640"]
        )
        self.assertTrue(self.settings.uses_single_site)

    @override_settings(WAGTAIL_SHAREPOINT={**BASE_SETTINGS, "SITE_IDS": ("a", "b")})
    def test_sited_ids__with_multiple_sites(self):
        self.assertEqual(self.settings.site_ids, ["a", "b"])
        self.assertIsInstance(self.settings.site_ids, list)
        self.assertFalse(self.settings.uses_single_site)

    @override_settings(
        WAGTAIL_SHAREPOINT={**BASE_SETTINGS, "SITE_ID": "a", "SITE_IDS": ["b", "c"]}
    )
    def test_site_id_takes_precedence_over_site_ids(self):
        self.assertEqual(self.settings.site_ids, ["a"])

    @override_settings(WAGTAIL_SHAREPOINT={**BASE_SETTINGS, "SITE_ID": ""})
    def test_site_ids__with_no_sites(self):
        self.assertEqual(self.settings.site_ids, [])
        self.assertFalse(self.settings.uses_single_site)

    def test_search_region(self):
        self.assertEqual(self.settings.search_region, "GBR")

        with override_settings(
            WAGTAIL_SHAREPOINT={**BASE_SETTINGS, "SEARCH_REGION": "NAM"}
        ):
            self.assertEqual(self.settings.search_region, "NAM")

    def test_cache_enabled(self):
        # Caching can only be switched off in DEBUG; DISABLE_CACHE is ignored
        # in production so a stray setting can't hammer the Graph API.
        not_set = object()
        cases = [
            # (DEBUG, DISABLE_CACHE, expected cache_enabled)
            (False, not_set, True),
            (False, False, True),
            (False, True, True),
            (True, not_set, True),
            (True, False, True),
            (True, True, False),
        ]
        for debug, disable_cache, expected in cases:
            user_settings = dict(BASE_SETTINGS)
            if disable_cache is not not_set:
                user_settings["DISABLE_CACHE"] = disable_cache

            with (
                self.subTest(debug=debug, disable_cache=disable_cache),
                override_settings(DEBUG=debug, WAGTAIL_SHAREPOINT=user_settings),
            ):
                self.assertIs(self.settings.cache_enabled, expected)

    def test_token_url(self):
        self.assertEqual(
            self.settings.token_url,
            "https://login.microsoftonline.com/test_tenant/oauth2/v2.0/token",
        )
