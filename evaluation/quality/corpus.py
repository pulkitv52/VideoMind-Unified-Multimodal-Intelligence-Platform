"""Freeze authorized originals and reviewable publisher/fixture qrels."""

import hashlib
import json
from evaluation.quality.labels import publisher_labels


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def freeze(client, root):
    w = client.get("/api/workspaces").json()[0]["id"]
    base = f"/api/workspaces/{w}"
    sources = client.get(base + "/sources")
    sources.raise_for_status()
    assets = []
    for source in sources.json():
        after = ""
        while True:
            r = client.get(
                base + f'/sources/{source["id"]}/assets',
                params={"limit": 200, **({"after": after} if after else {})},
            )
            r.raise_for_status()
            for item in r.json():
                if item.get("embedding_status") != "indexed":
                    raise ValueError("Freeze requires complete indexed originals")
                original = client.get(
                    base
                    + f'/sources/{source["id"]}/revisions/{item["revision_id"]}/original'
                )
                original.raise_for_status()
                if hashlib.sha256(original.content).hexdigest() != item["sha256"]:
                    raise ValueError("Original checksum mismatch")
                assets.append(
                    {
                        k: item[k]
                        for k in ("id", "title", "revision_id", "sha256", "modality")
                    }
                    | {
                        "source_id": source["id"],
                        "source_name": source["name"],
                        "bytes": len(original.content),
                    }
                )
            after = r.headers.get("x-next-cursor", "")
            if not after:
                break
    status = client.get(base + "/indexes")
    status.raise_for_status()
    active = next(g for g in status.json()["generations"] if g["status"] == "active")
    manifest = {
        "version": 1,
        "scope": "Authorized retained development corpus; not release gold",
        "workspace_id": w,
        "generation_id": active["id"],
        "profile": active["fingerprint"],
        "assets": sorted(assets, key=lambda a: a["id"]),
        "publisher_annotations": publisher_labels(root),
        "human_reviewers": [],
        "adjudicated": False,
        "training_contamination": "Unknown; no model-training exclusion claim",
    }
    manifest["sha256"] = hashlib.sha256(canonical(manifest)).hexdigest()
    return manifest


def queries(manifest):
    assets = manifest["assets"]
    output = []

    def add(
        family,
        slice_,
        texts,
        predicate,
        interval=None,
        filters=None,
        provenance="publisher_sequence_or_owned_fixture",
        split="development",
    ):
        relevant = [
            {
                "asset_id": a["id"],
                "revision_id": a["revision_id"],
                "grade": 3,
                **({"interval": interval} if interval else {}),
            }
            for a in assets
            if predicate(a)
        ]
        offset = sum(q["family"] == family for q in output)
        for n, query in enumerate(texts, start=offset):
            output.append(
                {
                    "id": f"{family}-{n+1}",
                    "family": family,
                    "slice": slice_,
                    "query": query,
                    "filters": filters or {},
                    "qrels": relevant,
                    "answerability": "positive" if relevant else "negative",
                    "label_provenance": provenance,
                    "split": split,
                    "human_reviewed": False,
                }
            )

    fight = next(
        a
        for a in manifest["publisher_annotations"]
        if a["asset_key"] == "caviar-Fight_Chase"
    )["intervals"][0]["interval"]
    add(
        "caviar-fight",
        "silent_video",
        [
            "two person fighting",
            "Two people fighting",
            "People fighting in an indoor lobby",
        ],
        lambda a: "Fight_Chase" in a["title"],
        fight,
        provenance="publisher_frame_hypotheses",
    )
    add(
        "urfall-fall",
        "silent_video",
        [
            "A person falling to the floor",
            "Someone loses balance and falls down",
            "A person collapses indoors",
        ],
        lambda a: a["title"].startswith("urfall-fall-"),
        provenance="publisher_sequence_class_no_temporal_label",
        split="heldout_family",
    )
    add(
        "caviar-walk",
        "silent_video",
        [
            "A person walking through a lobby",
            "People walking in an indoor entrance hall",
        ],
        lambda a: "caviar-Walk1__" in a["title"],
        provenance="publisher_frame_hypotheses",
    )
    for period, text in (
        ("day", "Driving along a road during the day"),
        ("night", "Dashcam footage of driving at night"),
    ):
        add(
            "roadscapes-driving",
            "silent_video",
            [text],
            lambda a, period=period: a["title"].startswith(
                "roadscapes-" + period + "_"
            ),
            provenance="sequence_name_only_requires_review",
            split="heldout_family",
        )
    add(
        "owned-safety",
        "document",
        [
            "How do I safely open the electrical panel?",
            "Switch off power before opening the safety panel",
        ],
        lambda a: a["title"] in ("procedure.txt", "scanned-page.pdf"),
    )
    add(
        "owned-speech",
        "spoken_video",
        [
            "How do I safely open the electrical panel?",
            "Turn off the power before opening the panel",
        ],
        lambda a: a["title"] == "spoken.mp4",
        filters={"modalities": ["video"]},
    )
    add(
        "owned-beeps",
        "audio",
        ["Repeated electronic beeping tones", "A series of electronic beeps"],
        lambda a: a["title"] == "beeps.wav",
    )
    add(
        "public-cat",
        "image",
        [
            "A close-up photograph of an orange cat",
            "An orange cat looking at the camera",
        ],
        lambda a: a["title"] == "chelsea.png",
    )
    add(
        "owned-square",
        "silent_video",
        ["A red square moving across a white background", "A moving red square"],
        lambda a: a["title"] in ("silent.mp4", "spoken.mp4"),
        [0, 4000],
        {"modalities": ["video"], "representations": ["video"]},
    )
    add(
        "identifiers",
        "identifier",
        ["caviar-Fight_Chase__derived.mp4"],
        lambda a: a["title"] == "caviar-Fight_Chase__derived.mp4",
    )
    add(
        "identifiers",
        "identifier",
        ["procedure.txt"],
        lambda a: a["title"] == "procedure.txt",
    )
    for n, text in enumerate(
        [
            "A submarine beneath Arctic ice",
            "A giraffe eating leaves in the savanna",
            "An astronaut repairing a satellite",
            "A violinist performing on a concert stage",
            "A volcano erupting beside a glacier",
            "A recipe for strawberry cheesecake",
            "person walking on roof",
            "A helicopter rescuing a sailor",
        ]
    ):
        add(
            f"negative-{n+1}",
            "negative",
            [text],
            lambda a: False,
            provenance="agent_proposed_absence_requires_human_review",
        )
    return {
        "version": 1,
        "corpus_sha256": manifest["sha256"],
        "scope": "Provisional development qrels; no independent human adjudication; heldout families are diagnostic only",
        "queries": output,
    }
