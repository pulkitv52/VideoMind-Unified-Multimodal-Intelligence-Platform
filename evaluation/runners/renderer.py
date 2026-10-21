"""Exercise a locally extracted LibreOffice build on a generated DOCX fixture."""

import hashlib
import json
import os
import re
import socket
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]


def prepare_tools():
    tools = ROOT / ".cache/system-tools"
    for package in sorted((ROOT / ".cache/system-debs").glob("*.deb")):
        subprocess.run(["dpkg-deb", "-x", str(package), str(tools)], check=True)
    # Relocate absolute package links only when their target is also in our cache.
    for directory, _, names in os.walk(tools, followlinks=False):
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                target = os.readlink(path)
                cached_target = tools / target.lstrip("/")
                if target.startswith("/") and cached_target.exists():
                    path.unlink()
                    path.symlink_to(os.path.relpath(cached_target, path.parent))
    configuration = tools / "usr/lib/libreoffice/program/fundamentalrc"
    text = configuration.read_text()
    for prefix in ("/usr", "/etc"):
        text = text.replace("file://" + prefix, (tools / prefix.lstrip("/")).as_uri())
    # dpkg post-install scripts normally populate /etc's registry links. Local
    # extraction does not run them, so use the packaged read-only registry.
    text = text.replace(
        (tools / "etc/libreoffice/registry").as_uri(),
        (tools / "usr/lib/libreoffice/share/.registry").as_uri(),
    )
    configuration.write_text(text)
    return tools


def make_docx(path):
    content_types = """<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>"""
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>"""
    document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>VideoMind renderer smoke test</w:t></w:r></w:p><w:p><w:r><w:t>Switch off the power before opening the safety panel.</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>"""
    document = document.replace(
        "<w:r><w:t>",
        '<w:r><w:rPr><w:rFonts w:ascii="DejaVu Sans" w:hAnsi="DejaVu Sans"/></w:rPr><w:t>',
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)


def renderer_environment(tools):
    program = tools / "usr/lib/libreoffice/program"
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        (str(program), str(tools / "usr/lib/x86_64-linux-gnu"))
    )
    env["SAL_USE_VCLPLUGIN"] = "svp"
    runtime = tools.parent / "libreoffice-runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = str(runtime)
    env["XDG_CACHE_HOME"] = str(tools.parent / "libreoffice-user-cache")
    return env


def check_local_ipc():
    # LibreOffice uses a local Unix socket even for offline headless conversion.
    path = ROOT / ".cache" / f"renderer-ipc-{os.getpid()}"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.bind(str(path))
    except PermissionError as exc:
        raise RuntimeError(
            "Renderer requires local Unix socket IPC; this environment denies it"
        ) from exc
    finally:
        path.unlink(missing_ok=True)


def main():
    report = {"status": "error"}
    try:
        check_local_ipc()
        tools = prepare_tools()
        program = tools / "usr/lib/libreoffice/program"
        executable = program / "soffice"
        env = renderer_environment(tools)
        version = subprocess.run(
            [
                str(executable),
                "--headless",
                "-env:UserInstallation="
                + (ROOT / ".cache/libreoffice-profile").as_uri(),
                "--version",
            ],
            env=env,
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        directory = ROOT / "evaluation/fixtures/generated/renderer"
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / "renderer-smoke.docx"
        make_docx(source)
        output = source.with_suffix(".pdf")
        # A stale file must not turn a failed conversion into a passing probe.
        output.unlink(missing_ok=True)
        conversion = subprocess.run(
            [
                str(executable),
                "--headless",
                "-env:UserInstallation="
                + (ROOT / ".cache/libreoffice-profile").as_uri(),
                "--convert-to",
                "pdf",
                "--outdir",
                str(directory),
                str(source),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        text = subprocess.run(
            ["pdftotext", str(output), "-"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
        info = subprocess.run(
            ["pdfinfo", str(output)],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
        pages = int(re.search(r"^Pages:\s+(\d+)", info, re.MULTILINE).group(1))
        fonts = subprocess.run(
            ["pdffonts", str(output)],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout
        report = {
            "status": "measured",
            "version": version.stdout.strip(),
            "conversion_output": conversion.stdout + conversion.stderr,
            "pdf_text": text,
            "pdf_info": info,
            "pages": pages,
            "fonts": fonts,
            "font_sha256": hashlib.sha256(
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf").read_bytes()
            ).hexdigest(),
            "sanity_passed": pages == 1
            and "DejaVuSans" in fonts
            and "VideoMind renderer smoke test" in text
            and "Switch off the power before opening the safety panel." in text,
            "docx_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "pdf_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["stderr"] = getattr(exc, "stderr", None)
        report["stdout"] = getattr(exc, "stdout", None)
    report["packages_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT / ".cache/system-debs").glob("*.deb"))
    }
    (ROOT / "evaluation/reports/renderer.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"packages_sha256", "conversion_output"}
            },
            indent=2,
        )
    )
    return 0 if report.get("sanity_passed", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
