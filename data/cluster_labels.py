"""Cluster embedded labels. The most common spelling in a cluster is its provisional name.

No model call. A later naming pass can replace the provisional name. Threshold is
cosine similarity to the cluster centroid.
"""

import json
import re
from pathlib import Path

import numpy as np

from r2_config import ROOT

EMB = ROOT / "data" / "extract" / "embeddings"
OUT = ROOT / "data" / "extract" / "aliases.jsonl"
CANON = ROOT / "data" / "extract" / "canonical.jsonl"
CLEAN = ROOT / "data" / "extract" / "facets_clean.jsonl"
THRESHOLD = {"problem": 0.86, "method": 0.86, "dataset": 0.88, "metric": 0.88}
DIGITS = re.compile(r"\d+")
TYPES = ("problem", "method", "dataset", "metric")
GROUPS = {
    "problem": ("problems_addressed",),
    "method": ("techniques_used", "baselines_compared"),
    "dataset": ("datasets_evaluated",),
    "metric": ("scoring_measures",),
}


def label_counts():
    counts = {kind: {} for kind in TYPES}
    with CLEAN.open(encoding="utf-8") as fh:
        for line in fh:
            facets = json.loads(line)["facets"]
            for kind, keys in GROUPS.items():
                for key in keys:
                    for item in facets.get(key) or []:
                        folded = item["label"].strip().casefold()
                        counts[kind][folded] = counts[kind].get(folded, 0) + 1
    return counts


def digit_set(label):
    return set(DIGITS.findall(label))


def assign(unit, labels, frequency_order, threshold):
    dim = unit.shape[1]
    centroid = np.empty((len(unit), dim), dtype=np.float32)
    counts = np.zeros(len(unit), dtype=np.int32)
    seeds = []
    members = []
    n = 0
    for index in frequency_order:
        vector = unit[index]
        digits = digit_set(labels[index])
        joined = False
        if n:
            scores = centroid[:n] @ vector
            for choice in np.argsort(-scores)[:8]:
                best = int(choice)
                if float(scores[best]) < threshold:
                    break
                seed_digits = digit_set(labels[seeds[best]])
                if digits and seed_digits and digits != seed_digits:
                    continue
                if digits and not seed_digits:
                    clash = any(
                        digit_set(labels[member]) and digit_set(labels[member]) != digits
                        for member in members[best]
                    )
                    if clash:
                        continue
                members[best].append(int(index))
                counts[best] += 1
                centroid[best] += (vector - centroid[best]) / counts[best]
                centroid[best] /= np.linalg.norm(centroid[best])
                joined = True
                break
        if joined:
            continue
        centroid[n] = vector
        counts[n] = 1
        seeds.append(int(index))
        members.append([int(index)])
        n += 1
    return members


def main():
    counts = label_counts()
    alias_lines = []
    canon_lines = []
    report = {}
    for kind in TYPES:
        labels = json.loads((EMB / f"{kind}_labels.json").read_text(encoding="utf-8"))
        vectors = np.load(EMB / f"{kind}_vectors.npy")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        unit = vectors / np.clip(norms, 1e-9, None)
        order = sorted(range(len(labels)), key=lambda i: (-counts[kind].get(labels[i].casefold(), 1), labels[i].casefold()))
        members = assign(unit, labels, order, THRESHOLD[kind])
        sizes = sorted((len(group) for group in members), reverse=True)
        report[kind] = {"labels": len(labels), "clusters": len(members), "largest": sizes[:8]}
        for cid, group in enumerate(members):
            ranked = sorted(group, key=lambda i: (-counts[kind].get(labels[i].casefold(), 1), len(labels[i])))
            name = labels[ranked[0]]
            canon_id = f"{kind}:{cid}"
            canon_lines.append(
                {"id": canon_id, "kind": kind, "name": name, "size": len(group), "provisional": True}
            )
            for index in group:
                alias_lines.append(
                    {
                        "kind": kind,
                        "label": labels[index],
                        "canonical_id": canon_id,
                        "canonical_name": name,
                    }
                )
        print(kind, report[kind], flush=True)
    with (ROOT / "data" / "extract" / "aliases.jsonl").open("w", encoding="utf-8") as fh:
        for row in alias_lines:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with CANON.open("w", encoding="utf-8") as fh:
        for row in canon_lines:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (EMB / "cluster_report.json").write_text(
        json.dumps({"threshold": THRESHOLD, "digit_guard": True, "kinds": report}, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
