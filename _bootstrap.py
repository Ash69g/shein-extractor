from pathlib import Path
import sys


def ensure_src_path() -> None:
    source_directory = Path(__file__).resolve().parent / "src"
    source = str(source_directory)
    if source not in sys.path:
        sys.path.insert(0, source)

