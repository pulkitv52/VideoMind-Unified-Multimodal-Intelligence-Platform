"""Publisher XML frames mapped through retained integer PTS; no guessed fps."""

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def checked(root, record):
    path = (root / record["path"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("manifest path escapes root")
    if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("manifest checksum mismatch")
    return path


def intervals(xml_path, mapping, term):
    frames = {
        int(f.attrib["number"])
        for f in ET.parse(xml_path).getroot().findall("frame")
        if any((e.text or "").strip() == term for e in f.findall(".//hypothesis/*"))
    }
    mapped = {row["source_frame"]: row for row in mapping}
    if not frames.issubset(mapped):
        raise ValueError("annotation frame has no mapping")

    def millis(row):
        return round(
            Fraction(row["derivative_pts"])
            * Fraction(row["derivative_time_base"])
            * 1000
        )

    ordered = sorted(frames)
    runs = []
    for number in ordered:
        if runs and number == runs[-1][-1] + 1:
            runs[-1].append(number)
        else:
            runs.append([number])
    result = []
    for run in runs:
        last = run[-1]
        following = mapped.get(last + 1)
        if following is None:
            raise ValueError("annotation end lacks exclusive next-frame boundary")
        result.append(
            {
                "start_frame": run[0],
                "last_inclusive_frame": last,
                "interval": [millis(mapped[run[0]]), millis(following)],
                "label": term,
                "provenance": "publisher_frame_hypotheses",
            }
        )
    return result


def publisher_labels(root):
    manifest = json.loads((root / "evaluation/manifests/video30.json").read_text())
    records = manifest["assets"] if "assets" in manifest else manifest["items"]
    output = []
    for asset in records:
        if asset["id"] not in ("caviar-Fight_Chase", "caviar-Walk1"):
            continue
        annotation = checked(root, asset["annotation"])
        checked(root, asset["derivative"])
        mapping_path = root / asset["derivative"]["mapping_path"]
        if (
            hashlib.sha256(mapping_path.read_bytes()).hexdigest()
            != asset["derivative"]["mapping_sha256"]
        ):
            raise ValueError("mapping checksum")
        mapping = json.loads(mapping_path.read_text())["mapping"]
        label = "fighting" if "Fight" in asset["id"] else "walking"
        output.append(
            {
                "asset_key": asset["id"],
                "annotation_sha256": asset["annotation"]["sha256"],
                "mapping_sha256": asset["derivative"]["mapping_sha256"],
                "intervals": intervals(annotation, mapping, label),
                "license": asset["license"],
                "homepage": asset["homepage"],
            }
        )
    return output
