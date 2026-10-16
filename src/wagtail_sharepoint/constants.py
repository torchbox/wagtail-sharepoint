SITES_CACHE_TTL = 24 * 60 * 60  # 1 day
SHORT_CACHE_TTL = 5 * 60  # 5 minutes

DOCUMENT_FIELDS = (
    "id,name,title,webUrl,size,lastModifiedDateTime,file,folder,parentReference"
)
DOCUMENT_SEARCH_FIELDS = [
    "id",
    "name",
    "size",
    "file",
    "webUrl",
    "createdDateTime",
    "lastModifiedDateTime",
    "parentReference",
]
PAGE_FIELDS = (
    "id,title,webUrl,createdBy,createdDateTime,lastModifiedDateTime,parentReference"
)
PAGE_SEARCH_FIELDS = [
    "id",
    "title",
    "webUrl",
    "createdDateTime",
    "lastModifiedDateTime",
    "parentReference",
    "createdBy",
]
SITE_FIELDS = "id,name,displayName,webUrl"

PK_SEPARATOR = "::"
