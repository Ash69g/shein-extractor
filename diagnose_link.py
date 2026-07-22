from _bootstrap import ensure_src_path

ensure_src_path()

from shein_extractor.infrastructure.diagnostics.link_diagnostics import (  # noqa: E402,F401
    inspect_with_browser,
    main,
    parse_bridge_url,
    resolve_with_http,
    validate_shein_url,
    write_report,
)

__all__ = [
    "inspect_with_browser",
    "main",
    "parse_bridge_url",
    "resolve_with_http",
    "validate_shein_url",
    "write_report",
]


if __name__ == "__main__":
    main()
