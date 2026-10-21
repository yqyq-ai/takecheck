"""ComfyUI entry point for the TakeCheck node.

ComfyUI imports this directory as a package and reads ``NODE_CLASS_MAPPINGS``.
Import failures are printed loudly instead of swallowed: a node that silently
disappears from the menu is very hard for a user to diagnose.
"""

import sys
import traceback
from pathlib import Path

__version__ = "0.1.0"

_HERE = Path(__file__).resolve().parent


def _require_takecheck() -> None:
    """Give a clear message when a dependency is missing."""
    try:
        import torch  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on the host install
        raise ImportError(
            "ComfyUI-TakeCheck needs PyTorch, which every ComfyUI install has.\n"
            "If you are running this outside ComfyUI, install it with:\n"
            f'  "{sys.executable}" -m pip install torch\n'
            f"(original error: {exc})"
        ) from exc

    try:
        import takecheck  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on the host install
        raise ImportError(
            "ComfyUI-TakeCheck needs the `takecheck` package.\n"
            "Install it into ComfyUI's Python with:\n"
            f'  "{sys.executable}" -m pip install takecheck\n'
            f"(original error: {exc})"
        ) from exc


try:
    _require_takecheck()
    from .TakeCheck import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # noqa: F401
except Exception as exc:  # pragma: no cover - surfaced in the ComfyUI console
    print("\n[TakeCheck] Failed to load the node:", file=sys.stderr)
    traceback.print_exc()
    # Show the actionable message, not just the underlying ImportError.
    message = str(exc)
    if "install" in message:
        print(f"\n[TakeCheck] {message}\n", file=sys.stderr)
    else:
        print(
            "[TakeCheck] Install the dependency with:\n"
            f'  "{sys.executable}" -m pip install takecheck\n',
            file=sys.stderr,
        )
    NODE_CLASS_MAPPINGS: dict = {}
    NODE_DISPLAY_NAME_MAPPINGS: dict = {}

WEB_DIRECTORY = None

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
    "WEB_DIRECTORY",
    "__version__",
    "_HERE",
]
