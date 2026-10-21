"""Offline regression against the real extracted LibreOffice distribution."""

import subprocess

import pytest

from evaluation.runners.renderer import (
    ROOT,
    renderer_environment,
    prepare_tools,
    main,
    check_local_ipc,
)

TOOLS = ROOT / ".cache/system-tools"
BINARY = TOOLS / "usr/lib/libreoffice/program/soffice.bin"


@pytest.mark.skipif(
    not BINARY.exists(), reason="pinned LibreOffice packages not cached"
)
def test_extracted_renderer_bootstraps(tmp_path):
    prepare_tools()
    result = subprocess.run(
        [
            str(BINARY),
            "--headless",
            "-env:UserInstallation=" + tmp_path.as_uri(),
            "--version",
        ],
        env=renderer_environment(TOOLS),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LibreOffice 24.2.7" in result.stdout


@pytest.mark.skipif(
    not BINARY.exists(), reason="pinned LibreOffice packages not cached"
)
def test_docx_conversion_preserves_page_and_text():
    try:
        check_local_ipc()
    except RuntimeError:
        pytest.skip("local Unix socket IPC denied in this sandbox")
    assert main() == 0
