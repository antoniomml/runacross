from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any, Protocol, cast

import boto3
from boto3.session import Session
from botocore.config import Config

from .models import coerce_regions
from .models import exclude_regions as drop_regions
from .sts import build_client_config

logger = logging.getLogger(__name__)

_ENABLED_REGION_STATUSES = ("ENABLED", "ENABLED_BY_DEFAULT")


class _Paginator(Protocol):
    def paginate(self, **kwargs: Any) -> Iterable[dict[str, Any]]:
        """Return all Account ListRegions response pages."""


class _AccountClient(Protocol):
    def get_paginator(self, operation_name: str) -> _Paginator:
        """Create a paginator for an Account Management operation."""


def list_enabled_regions(
    *,
    session: Session | None = None,
    botocore_config: Config | None = None,
    exclude_regions: Iterable[str] = (),
) -> list[str]:
    """List Regions enabled in the account of the supplied Session.

    Uses Account Management ``ListRegions`` and includes only
    ``ENABLED`` and ``ENABLED_BY_DEFAULT``. This queries AWS rather than
    Boto3 endpoint metadata.
    """

    excluded = coerce_regions(exclude_regions)
    source_session = session if session is not None else boto3.Session()
    client = cast(
        _AccountClient,
        source_session.client(
            "account",
            config=build_client_config(
                max_pool_connections=10,
                user_config=botocore_config,
            ),
        ),
    )

    names: list[str] = []
    paginator = client.get_paginator("list_regions")
    for page in paginator.paginate(
        RegionOptStatusContains=list(_ENABLED_REGION_STATUSES)
    ):
        for item in page.get("Regions", []):
            region_name = item.get("RegionName")
            if region_name is None:
                raise RuntimeError(
                    "AWS Account Management returned a Region without RegionName"
                )
            if not isinstance(region_name, str):
                raise RuntimeError(
                    "AWS Account Management returned a non-string RegionName"
                )
            names.append(region_name)

    enabled = drop_regions(coerce_regions(names), excluded)
    logger.debug("Discovered %d enabled Regions", len(enabled))
    return list(enabled)
