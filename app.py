from _bootstrap import ensure_src_path

ensure_src_path()

from shein_extractor.presentation.qt.bootstrap import main  # noqa: E402,F401
from shein_extractor.presentation.qt.main_window import MainWindow  # noqa: E402,F401

__all__ = ["MainWindow", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
