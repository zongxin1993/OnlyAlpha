"""Lean executable Provider read worker; never imports or replays the service entry point."""

from __future__ import annotations

import os
import pickle
import sys

_MAX_IPC_BYTES = 16 * 1024 * 1024


def _execute(factory: object, operation: str, request: object) -> tuple[str, tuple[object, ...]]:
    # Imports happen only after main has fenced stdout, including import-time plugin output.
    from dataclasses import replace
    from typing import cast

    from onlyalpha.domain.instrument import OnlyInstrument
    from onlyalpha.plugin.data_source import (
        OnlyDataSourceDiscovery,
        OnlyDataSourceDiscoveryCapabilitiesV1,
        OnlyDataSourceInstrumentCatalog,
        OnlyDataSourceInstrumentCatalogRequestV1,
        OnlyDataSourceInstrumentV1,
        OnlyDataSourceQuoteRequestV1,
        OnlyDataSourceQuotes,
        OnlyDataSourceQuoteV1,
    )

    _MAX_CATALOGUE = 10000
    try:
        result: tuple[object, ...]
        if operation in ("instruments", "discovery"):
            catalog_request = cast(OnlyDataSourceInstrumentCatalogRequestV1, request)
            capabilities = None
            if operation == "discovery":
                capabilities = cast(OnlyDataSourceDiscovery, factory).discovery_capabilities(
                    catalog_request.plugin_config
                )
                if type(capabilities) is not OnlyDataSourceDiscoveryCapabilitiesV1:
                    raise ValueError("DATA_SOURCE_DISCOVERY_CAPABILITIES_INVALID")
                capabilities.__post_init__()
                if (
                    catalog_request.asset_class is not None
                    and catalog_request.asset_class not in capabilities.asset_classes
                ):
                    return "COMPLETE", (capabilities, None)
                if capabilities.catalogue_snapshot:
                    catalog_request = replace(
                        catalog_request,
                        query="",
                        asset_class=None,
                        instrument_types=(),
                        limit=_MAX_CATALOGUE + 1,
                        snapshot=True,
                    )
            instruments = cast(OnlyDataSourceInstrumentCatalog, factory).list_instruments(catalog_request)
            if (
                not isinstance(instruments, tuple)
                or len(instruments) > _MAX_CATALOGUE + 1
                or any(
                    type(item) is not OnlyDataSourceInstrumentV1 or not isinstance(item.instrument, OnlyInstrument)
                    for item in instruments
                )
            ):
                raise ValueError("DISCOVERY_PROVIDER_RESPONSE_INVALID")
            result = (capabilities, instruments) if operation == "discovery" else instruments
        else:
            quote_request = cast(OnlyDataSourceQuoteRequestV1, request)
            if isinstance(factory, OnlyDataSourceDiscovery):
                capabilities = factory.discovery_capabilities(quote_request.plugin_config)
                if type(capabilities) is not OnlyDataSourceDiscoveryCapabilitiesV1:
                    raise ValueError("DATA_SOURCE_DISCOVERY_CAPABILITIES_INVALID")
                capabilities.__post_init__()
                if not capabilities.quotes:
                    return "UNSUPPORTED", ()
            result = cast(OnlyDataSourceQuotes, factory).quotes(quote_request)
            if (
                not isinstance(result, tuple)
                or len(result) > 25
                or any(type(item) is not OnlyDataSourceQuoteV1 for item in result)
            ):
                raise ValueError("DISCOVERY_PROVIDER_RESPONSE_INVALID")
        return "COMPLETE", result
    except Exception:
        return "UNAVAILABLE", ()


def main() -> None:
    # Only this private duplicated descriptor can write the bounded protocol reply.
    # Redirect FD 1 before unpickling: plugin imports and direct stdout.buffer writes
    # must not corrupt or enlarge the response pipe.
    with os.fdopen(os.dup(sys.stdout.fileno()), "wb") as output:
        with open(os.devnull, "wb") as discarded:
            os.dup2(discarded.fileno(), sys.stdout.fileno())
        try:
            request = sys.stdin.buffer.read(_MAX_IPC_BYTES + 1)
            if len(request) > _MAX_IPC_BYTES:
                raise ValueError("DISCOVERY_PROVIDER_REQUEST_TOO_LARGE")
            factory, operation, parameters = pickle.loads(request)
            payload = pickle.dumps(_execute(factory, operation, parameters))
            if len(payload) > _MAX_IPC_BYTES:
                raise ValueError("DISCOVERY_PROVIDER_RESPONSE_TOO_LARGE")
        except Exception:
            payload = pickle.dumps(("UNAVAILABLE", ()))
        output.write(payload)
        output.flush()


if __name__ == "__main__":
    main()
