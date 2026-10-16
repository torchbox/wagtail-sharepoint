# A Sharepoint document integration for Wagtail

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![PyPI version](https://img.shields.io/pypi/v/wagtail-sharepoint.svg?style=flat)](https://pypi.org/project/wagtail-sharepoint)
[![Build status](https://img.shields.io/github/actions/workflow/status/torchbox/wagtail-sharepoint/test.yml?branch=main)](https://github.com/torchbox/wagtail-sharepoint/actions)

## Links

- [Documentation](https://github.com/torchbox/wagtail-sharepoint/blob/main/README.md)
- [Changelog](https://github.com/torchbox/wagtail-sharepoint/blob/main/CHANGELOG.md)
- [Contributing](https://github.com/torchbox/wagtail-sharepoint/blob/main/CONTRIBUTING.md)
- [Discussions](https://github.com/torchbox/wagtail-sharepoint/discussions)
- [Security](https://github.com/torchbox/wagtail-sharepoint/security)

## Overview

`wagtail-sharepoint` provides a StreamField block choosers for SharePoint documents and choosers, allowing search
and selection of items across one or multiple SharePoint instances.

## Installation

In your project's Django settings, add the app your `INSTALLED_APPS` list (at the end is fine):

```python
INSTALLED_APPS = [
    # ...
    "wagtail_sharepoint",
]
```

Add the `SharepointDocumentChooserBlock` or `SharepointPageChooserBlock` block to your StreamField definition.
For example:

```python
# yourapp/models.py
from wagtail.fields import StreamField
from wagtail.models import Page

from wagtail_sharepoint.blocks import (
    SharepointDocumentChooserBlock,
    SharepointPageChooserBlock,
)


class WonderfulPage(Page):
    body = StreamField(
        [
            # ...
            ("sharepoint_document", SharepointDocumentChooserBlock()),
            ("sharepoint_page", SharepointPageChooserBlock()),
        ]
    )
```

Finally, run Django's `makemigrations` and `migrate` commands to apply any model field changes to your project

```sh
$ python manage.py makemigrations
$ python manage.py migrate
```

## Configuration

### Entra

To start with, you will need to configure an Entra application, to get a tenant id, client id and secret.

Permission scopes: `Sites.Read.All`, `Sites.ReadWrite.All`


### Wagtail settings

Add or update the `WAGTAIL_SHAREPOINT` configuration dictionary in your project's settings file.
The configuration dictionary has the following options:

```python
WAGTAIL_SHAREPOINT = {
    "TENANT_ID": "<Entra tenant id>",
    "CLIENT_ID": "<Entra client id>",
    "CLIENT_SECRET": "<Entra client secret>",
    "SITE_ID": "<instance id>",  # Either the Sharepoint instance id
    # OR
    "SITE_IDS": ["<instance_1_id>", "instance_2_id"],  # or a list of instance IDs
    "REGION": "<region here>",  # Optional. Defaults to "GBR"
    # for local development and debug. Works in conjunction with DEBUG=True
    "DISABLE_CACHE": False,  # Optional. Defaults to False.
}
```

A SharePoint site is identified by [a unique ID](https://learn.microsoft.com/en-us/graph/api/resources/site?view=graph-rest-1.0#id-property) that is a composite of the following values:
- Site collection hostname (e.g.`contoso.sharepoint.com`)
- Site collection unique ID (GUID. e.g. `f2f28bab-9c17-411d-bb28-2914b4957958`)
- Site unique ID (GUID. e.g. `aac37637-022b-45e3-9d25-59f7aa14d640`)

You can use the full ID (`contoso.sharepoint.com,f2f28bab-9c17-411d-bb28-2914b4957958,aac37637-022b-45e3-9d25-59f7aa14d640`),
the site collection id (`f2f28bab-9c17-411d-bb28-2914b4957958`) or the site unique id (`aac37637-022b-45e3-9d25-59f7aa14d640`).


## Contributing

All contributions are welcome! See [CONTRIBUTING.md](https://github.com/torchbox/wagtail-sharepoint/blob/main/CONTRIBUTING.md)

Supported versions:

- Python 3.12, 3.13, 3.14, 3.15
- Django 5.2, 6.0, 6.1
- Wagtail 7.4 (LTS), 8.0
