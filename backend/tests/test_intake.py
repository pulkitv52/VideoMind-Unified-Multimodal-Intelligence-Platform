from pathlib import Path
import zipfile

import pytest

from videomind.connectors.local_folder.reader import files, relative_folder
from videomind.connectors.upload.validation import InvalidFile, inspect, filename


def test_signatures_paths_and_text_are_validated(tmp_path):
    path = tmp_path / "input"
    path.write_bytes(b"plain text")
    assert inspect(path, "notes.md") == ("text/markdown", "document")
    for name in ("../../escape.pdf", "x\\a.pdf", "bad\nname.txt"):
        with pytest.raises(InvalidFile):
            filename(name)
    for name in ("fake.png", "script.exe", "fake.pdf"):
        with pytest.raises(InvalidFile):
            inspect(path, name)
    path.write_bytes(b"abc\x00def")
    with pytest.raises(InvalidFile):
        inspect(path, "notes.txt")
    path.write_bytes(b"\xff")
    with pytest.raises(InvalidFile):
        inspect(path, "notes.txt")


def test_docx_archive_budget_and_macro_guard(tmp_path):
    path = tmp_path / "input"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
    assert inspect(path, "notes.docx")[1] == "document"
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr("word/vbaProject.bin", "macro")
    with pytest.raises(InvalidFile):
        inspect(path, "notes.docx")


def test_folder_reader_rejects_traversal_and_symlinks(tmp_path):
    root = tmp_path / "imports"
    root.mkdir()
    (root / "safe.txt").write_text("original")
    found = list(
        (external, name, size, stream.read())
        for external, name, size, stream in files(root, "")
    )
    assert found == [("safe.txt", "safe.txt", 8, b"original")]
    for path in ("../outside", "/etc", "safe/../outside", "bad\\path"):
        with pytest.raises(InvalidFile):
            relative_folder(path)
    outside = tmp_path / "outside"
    outside.write_text("private")
    (root / "link.txt").symlink_to(outside)
    with pytest.raises((InvalidFile, OSError)):
        list(files(root, ""))
    (root / "link.txt").unlink()
    target = tmp_path / "outside-dir"
    target.mkdir()
    (root / "link").symlink_to(target, target_is_directory=True)
    with pytest.raises(InvalidFile):
        list(files(root, ""))
