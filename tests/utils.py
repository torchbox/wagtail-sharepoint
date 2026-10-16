import copy

from typing import Any

import responses

from responses import matchers


API_ROOT = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/test_tenant/oauth2/v2.0/token"  # noqa: S105
SITES_URL = f"{API_ROOT}/sites/getAllSites"
SEARCH_URL = f"{API_ROOT}/search/query"

TOKEN = "test-access-token"  # noqa: S105

SHAREPOINT_HOST = "contoso.sharepoint.com"

# Sharepoint site ids are "<hostname>,<site collection id>,<web id>"
TEST_COLLECTION_ID = "0d3a7a6e-5c3b-4a0f-9c1e-111111111111"
TEST_SITE_UID = "aac37637-022b-45e3-9d25-59f7aa14d640"
TEST_SITE_ID = f"{SHAREPOINT_HOST},{TEST_COLLECTION_ID},{TEST_SITE_UID}"
TEST_SITE_URL = f"https://{SHAREPOINT_HOST}/sites/test-site"

EXTRA_SITE_COLLECTION_ID = "6f1c2b9d-8e4a-4d7b-b2a0-222222222222"
EXTRA_SITE_UID = "b7d4e8f2-1a3c-4e5b-9d6f-333333333333"
EXTRA_SITE_ID = f"{SHAREPOINT_HOST},{EXTRA_SITE_COLLECTION_ID},{EXTRA_SITE_UID}"
EXTRA_SITE_URL = f"https://{SHAREPOINT_HOST}/sites/extra-site"

# Visible to the app registration but never configured
UNUSED_SITE_ID = f"{SHAREPOINT_HOST},9a9a9a9a-0000-0000-0000-444444444444,9b9b9b9b-0000-0000-0000-555555555555"
UNUSED_SITE_URL = f"https://{SHAREPOINT_HOST}/sites/unused-site"

TEST_SITE = {"id": TEST_SITE_ID, "name": "Test site", "webUrl": TEST_SITE_URL}
EXTRA_SITE = {"id": EXTRA_SITE_ID, "name": "Extra site", "webUrl": EXTRA_SITE_URL}
UNUSED_SITE = {"id": UNUSED_SITE_ID, "name": "Not used", "webUrl": UNUSED_SITE_URL}
ALL_SITES = [TEST_SITE, EXTRA_SITE, UNUSED_SITE]

DRIVE_ID = "b!testDrive"
EXTRA_DRIVE_ID = "b!extraDrive"

BASE_SETTINGS = {
    "TENANT_ID": "test_tenant",
    "CLIENT_ID": "test_client_id",
    "CLIENT_SECRET": "test_not_a_secret",
}
SINGLE_SITE_SETTINGS = {**BASE_SETTINGS, "SITE_ID": TEST_SITE_UID}
MULTI_SITE_SETTINGS = {**BASE_SETTINGS, "SITE_IDS": [TEST_SITE_UID, EXTRA_SITE_UID]}


def get_document_data(
    item_id="01DOC0001",
    name="Annual report.pdf",
    *,
    drive_id=DRIVE_ID,
    site_url=TEST_SITE_URL,
    size=2048,
    mime_type="application/pdf",
    **extra,
) -> dict:
    data = {
        "id": item_id,
        "name": name,
        "webUrl": f"{site_url}/Shared Documents/{name}",
        "size": size,
        "file": {"mimeType": mime_type},
        "createdDateTime": "2026-01-11T09:30:00Z",
        "lastModifiedDateTime": "2026-02-20T16:45:00Z",
        "parentReference": {"driveId": drive_id},
    }
    data.update(extra)
    return data


def get_page_data(
    item_id="0a1b2c3d-page-0001",
    title="Welcome",
    *,
    site_id=TEST_SITE_ID,
    site_url=TEST_SITE_URL,
    **extra,
) -> dict:
    data = {
        "id": item_id,
        "title": title,
        "webUrl": f"{site_url}/SitePages/{title}.aspx",
        "createdDateTime": "2025-03-01T08:00:00Z",
        "lastModifiedDateTime": "2025-03-05T12:15:00Z",
        "parentReference": {"siteId": site_id},
    }
    data.update(extra)
    return data


def search_payload(
    resources: list[dict[str, Any]], total: int | None = None, *, more: bool = False
) -> dict:
    return {
        "value": [
            {
                "hitsContainers": [
                    {
                        "hits": [
                            {"hitId": r["id"], "resource": copy.deepcopy(r)}
                            for r in resources
                        ],
                        "total": len(resources) if total is None else total,
                        "moreResultsAvailable": more,
                    }
                ]
            }
        ]
    }


def mock_token_response(token=TOKEN, expires_in=3600, **kwargs):
    return responses.post(
        TOKEN_URL,
        json={"token_type": "Bearer", "expires_in": expires_in, "access_token": token},
        **kwargs,
    )


def mock_sites_response(sites=None, **kwargs):
    return responses.get(
        SITES_URL,
        json={"value": copy.deepcopy(ALL_SITES if sites is None else sites)},
        **kwargs,
    )


def mock_search_response(resources=(), total=None, *, more=False, **kwargs):
    return responses.post(
        SEARCH_URL, json=search_payload(list(resources), total, more=more), **kwargs
    )


def mock_drive_item_response(data, drive_id=DRIVE_ID, **kwargs):
    return responses.get(
        f"{API_ROOT}/drives/{drive_id}/items/{data['id']}", json=data, **kwargs
    )


def mock_page_response(data, site_id=TEST_SITE_ID, **kwargs):
    return responses.get(
        f"{API_ROOT}/sites/{site_id}/pages/{data['id']}/microsoft.api_client.sitePage",
        json=data,
        **kwargs,
    )


def bearer_matcher(token=TOKEN):
    return matchers.header_matcher({"Authorization": f"Bearer {token}"})


def search_bodies() -> list[dict]:
    """Decoded JSON bodies of every /search/query call made so far."""
    import json

    return [
        json.loads(call.request.body)
        for call in responses.calls
        if call.request.url == SEARCH_URL
    ]
