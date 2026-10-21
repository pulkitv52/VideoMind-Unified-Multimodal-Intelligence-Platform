"""Prepare bounded CAVIAR, UR Fall and Roadscapes intake samples."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / ".local/datasets/video30"
MANIFEST = ROOT / "evaluation/manifests/video30.json"
CAVIAR_PAGE = "https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/CAVIARDATA1/"
UR_PAGE = "https://fenix.ur.edu.pl/mkepski/ds/uf.html"

CAVIAR = [
    (
        "EnterExitCrossingPaths1cor",
        "CAVIARDATA2",
        "shop_entry_crossing",
        "ceecp1gt.xml",
    ),
    ("OneLeaveShop1cor", "CAVIARDATA2", "shop_exit", "cols1gt.xml"),
    ("OneLeaveShopReenter1cor", "CAVIARDATA2", "shop_reentry", "colsr1gt.xml"),
    ("OneShopOneWait1cor", "CAVIARDATA2", "waiting_outside_shop", "cosow1gt.xml"),
    ("OneStopEnter1cor", "CAVIARDATA2", "shop_entry", "cose1gt.xml"),
    (
        "OneStopMoveEnter1cor",
        "CAVIARDATA2",
        "browsing_and_entering_shop",
        "cosme1gt.xml",
    ),
    ("ShopAssistant1cor", "CAVIARDATA2", "people_browsing_together", "csa1gt.xml"),
    ("ThreePastShop1cor", "CAVIARDATA2", "group_walking", "c3ps1gt.xml"),
    ("Walk1", "CAVIARDATA1", "walking", "wk1gt.xml"),
    ("Browse1", "CAVIARDATA1", "browsing", "br1gt.xml"),
    ("Rest_InChair", "CAVIARDATA1", "resting_in_chair", "ricgt.xml"),
    ("Rest_FallOnFloor", "CAVIARDATA1", "staged_fall", "rffgt.xml"),
    ("LeftBag", "CAVIARDATA1", "leaving_bag", "lb1gt.xml"),
    ("Meet_WalkSplit", "CAVIARDATA1", "meeting_and_separating", "mws1gt.xml"),
    ("Fight_Chase", "CAVIARDATA1", "staged_fight_and_chase", "fcgt.xml"),
]


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def download(url, path, maximum):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:
        return {
            "url": url,
            "bytes": path.stat().st_size,
            "sha256": sha(path),
            "path": str(path.relative_to(ROOT)),
        }
    part = path.with_suffix(path.suffix + ".part")
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "VideoMind-local-dataset-demo/1.0"}
            )
            with (
                urllib.request.urlopen(request, timeout=180) as response,
                part.open("wb") as output,
            ):
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > maximum:
                    raise ValueError("Published file exceeds per-file download budget")
                count = 0
                while chunk := response.read(64 * 1024):
                    count += len(chunk)
                    if count > maximum:
                        raise ValueError("Download budget exceeded")
                    output.write(chunk)
                if declared and count != int(declared):
                    raise ValueError("Incomplete download")
            part.replace(path)
            return {
                "url": url,
                "bytes": count,
                "sha256": sha(path),
                "path": str(path.relative_to(ROOT)),
            }
        except urllib.error.HTTPError as exc:
            part.unlink(missing_ok=True)
            if exc.code == 429:
                retry = exc.headers.get("Retry-After", "90")
                if not retry.isdigit() or int(retry) > 180 or attempt == 2:
                    raise
                print(
                    "Publisher rate limit; waiting",
                    max(60, int(retry)),
                    "seconds",
                    flush=True,
                )
                time.sleep(max(60, int(retry)))
                continue
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
        except Exception:
            part.unlink(missing_ok=True)
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def definitions():
    items = []
    for name, section, label, annotation in CAVIAR:
        base = f"https://groups.inf.ed.ac.uk/vision/DATASETS/CAVIAR/{section}/{name}/"
        items.append(
            {
                "id": "caviar-" + name,
                "dataset": "CAVIAR",
                "class_hint": label,
                "label_kind": "publisher_sequence_description",
                "homepage": CAVIAR_PAGE,
                "license": "CC BY-SA (publisher page does not identify version)",
                "credit": "EC Funded CAVIAR project / IST 2001 37540; INRIA and Lisbon shopping-centre sequences",
                "original_url": base + name + ".mpg",
                "original_filename": name + ".mpg",
                "annotation_url": base + annotation,
                "annotation_filename": annotation,
            }
        )
    for kind in ("fall", "adl"):
        for index in (range(1, 6) if kind == "fall" else (1, 2, 3, 24, 28)):
            name = f"{kind}-{index:02d}"
            items.append(
                {
                    "id": "urfall-" + name,
                    "dataset": "UR Fall",
                    "class_hint": "staged_fall" if kind == "fall" else "daily_activity",
                    "label_kind": "publisher_fall_vs_adl_sequence_label",
                    "homepage": UR_PAGE,
                    "license": "CC BY-NC-SA 4.0; noncommercial academic use",
                    "credit": "Bogdan Kwolek and Michal Kepski; University of Rzeszow; cite Kwolek & Kepski (2014)",
                    "original_url": f"https://fenix.ur.edu.pl/mkepski/ds/data/{name}-cam0-rgb.zip",
                    "original_filename": name + "-cam0-rgb.zip",
                    "annotation_url": f"https://fenix.ur.edu.pl/mkepski/ds/data/{name}-data.csv",
                    "annotation_filename": name + "-data.csv",
                }
            )
    return items


def fetch(item):
    folder = DEST / "originals" / item["id"]
    folder.mkdir(parents=True, exist_ok=True)
    original = download(
        item["original_url"], folder / item["original_filename"], 150 * 1024**2
    )
    annotation = download(
        item["annotation_url"], folder / item["annotation_filename"], 16 * 1024**2
    )
    print(
        "Fetched", item["id"], round(original["bytes"] / 1024**2, 1), "MiB", flush=True
    )
    return dict(item, original=original, annotation=annotation)


def write_manifest(items):
    temporary = MANIFEST.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            {
                "scope": "Small local academic intake sample pack; not a retrieval or clinical benchmark",
                "items": items,
            },
            indent=2,
        )
        + "\n"
    )
    temporary.replace(MANIFEST)


def encode(frames, target, rate, time_map):
    import av

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".partial.mp4")
    count = 0
    last = -1
    try:
        with av.open(
            str(part), "w", format="mp4", options={"movflags": "+faststart"}
        ) as output:
            stream = None
            for frame, source_seconds, locator in frames:
                if stream is None:
                    stream = output.add_stream("libx264", rate=rate)
                    scale = min(1, 640 / frame.width)
                    stream.width = int(frame.width * scale) // 2 * 2
                    stream.height = int(frame.height * scale) // 2 * 2
                    stream.pix_fmt = "yuv420p"
                    stream.time_base = Fraction(1, 90000)
                    stream.codec_context.time_base = Fraction(1, 90000)
                    stream.codec_context.thread_count = 2
                    stream.codec_context.max_b_frames = 0
                    stream.options = {"crf": "23", "preset": "veryfast"}
                position = round(source_seconds * 90000)
                if position <= last:
                    raise ValueError("Nonmonotonic source frame timestamps")
                converted = frame.reformat(
                    width=stream.width, height=stream.height, format="yuv420p"
                )
                converted.pts = position
                converted.time_base = Fraction(1, 90000)
                for packet in stream.encode(converted):
                    output.mux(packet)
                time_map.append(
                    {
                        "derivative_frame": count,
                        "derivative_pts": position,
                        "derivative_time_base": "1/90000",
                        **locator,
                    }
                )
                count += 1
                last = position
                if count > 20000:
                    raise ValueError("Sample frame budget exceeded")
            if stream is None:
                raise ValueError("No video frames")
            for packet in stream.encode():
                output.mux(packet)
        part.replace(target)
    except Exception:
        part.unlink(missing_ok=True)
        raise
    if target.stat().st_size > 64 * 1024**2:
        raise ValueError("Derived clip exceeds upload limit")
    return count


def video_frames(path, repair_duplicates=False):
    import av

    with av.open(str(path)) as source:
        video = source.streams.video[0]
        first = None
        previous_source = None
        previous_playback_tick = -1
        for number, frame in enumerate(source.decode(video)):
            if frame.pts is None:
                raise ValueError("Video frame lacks original PTS")
            timestamp = Fraction(frame.pts) * frame.time_base
            if first is None:
                first = timestamp
            position = round((timestamp - first) * 90000)
            adjustment = 0
            if repair_duplicates and timestamp == previous_source:
                adjustment = previous_playback_tick + 1 - position
                position += adjustment
            previous_source = timestamp
            previous_playback_tick = position
            yield frame, position / 90000, {
                "playback_adjustment_ticks": adjustment,
                "source_frame": number,
                "source_pts": frame.pts,
                "source_time_base": str(frame.time_base),
            }


def rgb_frames(path, annotation):
    import av
    from PIL import Image

    rows = []
    for row in csv.reader(annotation.read_text().splitlines()):
        try:
            rows.append((int(row[0]), float(row[1])))
        except (ValueError, IndexError):
            continue
    if not rows:
        raise ValueError("Missing synchronization timestamps")
    timestamps = dict(rows)
    with zipfile.ZipFile(path) as archive:
        members = [i for i in archive.infolist() if i.filename.lower().endswith(".png")]
        if (
            not members
            or len(members) > 3000
            or sum(i.file_size for i in members) > 512 * 1024**2
        ):
            raise ValueError("RGB archive budget exceeded")
        members.sort(key=lambda x: int(re.findall(r"\d+", Path(x.filename).stem)[-1]))
        origin = None
        for index, entry in enumerate(members):
            if entry.file_size > 4 * 1024**2:
                raise ValueError("RGB image exceeds budget")
            number = int(re.findall(r"\d+", Path(entry.filename).stem)[-1])
            if number not in timestamps:
                raise ValueError(f"Frame {number} has no timestamp")
            ms = timestamps[number]
            if origin is None:
                origin = ms
            with Image.open(io.BytesIO(archive.read(entry))) as image:
                if image.width * image.height > 2_000_000:
                    raise ValueError("RGB pixel budget exceeded")
                frame = av.VideoFrame.from_image(image.convert("RGB"))
            yield frame, (ms - origin) / 1000, {
                "archive_member": entry.filename,
                "source_frame": number,
                "source_timestamp_ms": ms,
                "source_clock": "publisher sequence-relative synchronization CSV milliseconds",
            }


def convert(item):
    import av

    path = ROOT / item["original"]["path"]
    annotation = ROOT / item["annotation"]["path"] if item.get("annotation") else None
    target = DEST / "derived" / f"{item['id']}__derived.mp4"
    mapping = target.with_suffix(".mapping.json")
    if target.exists() and mapping.exists():
        result = json.loads(mapping.read_text())
        result.pop("mapping", None)
        if (
            result["original_sha256"] != item["original"]["sha256"]
            or sha(target) != result["sha256"]
        ):
            raise ValueError("Cached derivative integrity mismatch")
        return dict(
            item,
            derivative=dict(
                result,
                mapping_path=str(mapping.relative_to(ROOT)),
                mapping_sha256=sha(mapping),
            ),
        )
    time_map = []
    if item["dataset"] == "UR Fall":
        frames = rgb_frames(path, annotation)
        rate = Fraction(30, 1)
        audio_streams = 0
    else:
        with av.open(str(path)) as source:
            rate = source.streams.video[0].average_rate or Fraction(25, 1)
            audio_streams = len(source.streams.audio)
        frames = video_frames(path, repair_duplicates=True)
    count = encode(frames, target, rate, time_map)
    with av.open(str(target)) as check:
        decoded = list(
            (frame.pts, str(frame.time_base)) for frame in check.decode(video=0)
        )
        if len(decoded) != count:
            raise ValueError("Derived frame count mismatch")
        for actual, expected in zip(decoded, time_map):
            if (
                abs(
                    float(Fraction(actual[0]) * Fraction(actual[1]))
                    - expected["derivative_pts"] / 90000
                )
                > 1 / 1000
            ):
                raise ValueError("Derived time mapping mismatch")
    result = {
        "path": str(target.relative_to(ROOT)),
        "bytes": target.stat().st_size,
        "sha256": sha(target),
        "frames": count,
        "producer": "videomind-video30-pyav-v2",
        "timestamp_policy": "Preserve source PTS; separate duplicate playback timestamps by one 1/90000-second tick; reject backwards timestamps",
        "adjusted_frames": sum(
            bool(m.get("playback_adjustment_ticks")) for m in time_map
        ),
        "pyav_version": av.__version__,
        "encoding": {
            "codec": "libx264",
            "crf": 23,
            "preset": "veryfast",
            "max_width": 640,
            "threads": 2,
            "max_b_frames": 0,
        },
        "original_sha256": item["original"]["sha256"],
        "audio_policy": "video-only preview derivative; originals retained",
        "original_audio_streams": audio_streams,
        "mapping": time_map,
    }
    mapping.write_text(json.dumps(result, indent=2) + "\n")
    print("Converted", item["id"], count, "frames", flush=True)
    result.pop("mapping")
    return dict(
        item,
        derivative=dict(
            result,
            mapping_path=str(mapping.relative_to(ROOT)),
            mapping_sha256=sha(mapping),
        ),
    )


def fetch_roads():
    definition = json.loads(
        (ROOT / "docs/research/roadscapes-video-starter.json").read_text()
    )
    results = []
    for sample in definition["samples"]:
        identifier = sample["id"]
        filename = sample["title"]
        original = download(
            sample["media_url"],
            DEST / "originals" / identifier / filename,
            64 * 1024**2,
        )
        if (
            original["bytes"] != sample["bytes"]
            or original["sha256"] != sample["sha256"]
        ):
            raise ValueError("Road publisher checksum/size mismatch")
        item = {
            "id": identifier,
            "dataset": "Roadscapes",
            "class_hint": sample["title"],
            "label_kind": "publisher_sequence_name; AI annotations unverified",
            "homepage": sample["page_url"],
            "license": sample["license"],
            "license_url": sample["license_url"],
            "credit": sample["creator"],
            "original": original,
            "annotation": None,
            "source_metadata": sample,
        }
        results.append(item)
        (DEST / "roads.json").write_text(json.dumps(results, indent=2) + "\n")
        print("Fetched", identifier, flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["fetch", "convert", "fetch-roads", "merge"])
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    if args.action == "fetch":
        items = definitions()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = (
                {i["id"]: i for i in json.loads(MANIFEST.read_text())["items"]}
                if MANIFEST.exists()
                else {}
            )
            futures = {pool.submit(fetch, item): item for item in items}
            for future in as_completed(futures):
                result = future.result()
                previous = results.get(result["id"], {})
                if previous.get("original", {}).get("sha256") == result["original"][
                    "sha256"
                ] and previous.get("derivative"):
                    result["derivative"] = previous["derivative"]
                results[result["id"]] = result
                write_manifest(list(results.values()))
    elif args.action == "fetch-roads":
        fetch_roads()
    elif args.action == "merge":
        data = json.loads(MANIFEST.read_text())
        items = [
            i
            for i in data["items"]
            if i["dataset"] not in {"Commons road samples", "Roadscapes"}
        ]
        write_manifest(items + json.loads((DEST / "roads.json").read_text()))
    else:
        data = json.loads(MANIFEST.read_text())
        results = []
        for item in data["items"]:
            results.append(convert(item))
            write_manifest(results + data["items"][len(results) :])


if __name__ == "__main__":
    main()
