"""Shared test helpers.

`make_symlink` (issue #122): creating a symlink on Windows needs admin rights or Developer Mode, otherwise the OS
answers `OSError: [WinError 1314] A required privilege is not held by the client`. Tests that need a symlink create
it through this fixture, which skips the test with a clear reason only when the OS actually refuses. There is no
platform check: on macOS and Linux the link is created and the test runs as before; any other error still fails.

`_scratch_predictions_db` (autouse, issue #130): every test starts with FAULTLINE_PREDICTIONS_DB pointed at a fresh
temporary file outside the test's own `tmp_path`, so no test can write the official store
(services/api/var/predictions.sqlite3) by forgetting to configure one. Tests that need a specific store set the
variable themselves; tests about the default `monkeypatch.delenv` it and never open a store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Windows error code for "A required privilege is not held by the client".
WINERROR_PRIVILEGE_NOT_HELD = 1314
SKIP_REASON_WINERROR_1314 = "OS refused to create a symlink (Windows without Developer Mode/admin): WinError 1314"


def _refusal_reason(exc: BaseException) -> str | None:
    """Skip reason if `exc` means "this OS/user may not create symlinks", else None (the error is a real failure)."""
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == WINERROR_PRIVILEGE_NOT_HELD:
        return SKIP_REASON_WINERROR_1314
    if isinstance(exc, NotImplementedError):
        return f"OS refused to create a symlink: {type(exc).__name__}: {exc}"
    return None


def symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    """Create `link` -> `target`; skip the calling test only if the OS refuses to create symlinks."""
    try:
        Path(link).symlink_to(target, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        reason = _refusal_reason(exc)
        if reason is None:
            raise
        pytest.skip(reason)


@pytest.fixture
def make_symlink():
    """`make_symlink(link, target, target_is_directory=False)`: see `symlink_or_skip`."""
    return symlink_or_skip


@pytest.fixture(autouse=True)
def _scratch_predictions_db(tmp_path_factory, monkeypatch):
    monkeypatch.setenv(
        "FAULTLINE_PREDICTIONS_DB", str(tmp_path_factory.mktemp("predictions_db") / "predictions.sqlite3")
    )
