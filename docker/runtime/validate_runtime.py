#!/usr/bin/env python
import hashlib
import os
import sys

import numpy as np
import pandas as pd


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_descriptor(path):
    with np.load(path, allow_pickle=False) as data:
        if set(("x", "pdbs", "idxs")).difference(data.files):
            raise SystemExit("Descriptor lacks x, pdbs, or idxs")
        x, pdbs, idxs = data["x"], data["pdbs"], data["idxs"]
        if x.ndim != 2 or x.shape[1] != 512:
            raise SystemExit("Expected descriptor shape (N, 512), got %r" % (x.shape,))
        if len(x) == 0 or not (len(x) == len(pdbs) == len(idxs)):
            raise SystemExit("Descriptor arrays have inconsistent or empty lengths")
        if not np.isfinite(x).all():
            raise SystemExit("Descriptor contains NaN or Inf")
        unique, counts = np.unique(pdbs.astype(str), return_counts=True)
        print("descriptor_shape=%s" % (x.shape,))
        print("descriptor_dtype=%s" % x.dtype)
        print("descriptor_norm_min=%.6f" % np.linalg.norm(x, axis=1).min())
        print("descriptor_norm_max=%.6f" % np.linalg.norm(x, axis=1).max())
        for name, count in zip(unique, counts):
            print("patches[%s]=%d" % (name, count))


def validate_tsv(path, aligned=False):
    if not os.path.isfile(path):
        raise SystemExit("Missing TSV: %s" % path)
    frame = pd.read_csv(path, sep="\t")
    required = {
        "target", "library epitope", "target_nhits", "target_nexpanded",
        "mean_desc_dist", "library_nhits", "library_nexpanded",
        "frac_library_hits", "target_expanded_indices",
        "library_epitope_indices", "frac_expanded", "frac_geo",
    }
    if aligned:
        required.add("id")
    missing = required.difference(frame.columns)
    if missing:
        raise SystemExit("TSV missing columns: %s" % sorted(missing))
    numeric = [
        "target_nhits", "target_nexpanded", "mean_desc_dist", "library_nhits",
        "library_nexpanded", "frac_library_hits",
        "frac_expanded", "frac_geo",
    ]
    alignment_columns = {
        "aln1_score1", "aln1_score2", "aln1_score3",
        "aln1_normal_score", "aln1_ncontact",
    }
    if aligned and "id" in frame.columns:
        aligned_rows = pd.to_numeric(frame["id"], errors="coerce").fillna(-1) >= 0
        if aligned_rows.any():
            missing_alignment = alignment_columns.difference(frame.columns)
            if missing_alignment:
                raise SystemExit("Aligned rows lack columns: %s" % sorted(missing_alignment))
        numeric.extend(sorted(alignment_columns.intersection(frame.columns)))
    else:
        aligned_rows = pd.Series(True, index=frame.index)
    for column in numeric:
        values = pd.to_numeric(frame[column], errors="coerce")
        selected = values[aligned_rows] if column in alignment_columns else values
        if len(selected) and not np.isfinite(selected).all():
            raise SystemExit("Non-finite values in %s" % column)
    for column in ("frac_library_hits", "frac_expanded", "frac_geo"):
        values = pd.to_numeric(frame[column], errors="coerce")
        if len(values) and ((values < 0).any() or (values > 1).any()):
            raise SystemExit("Values outside [0,1] in %s" % column)
    print("rows=%d" % len(frame))
    print("columns=%d" % len(frame.columns))
    if len(frame):
        print("targets=%d" % frame["target"].nunique())
        print("libraries=%d" % frame["library epitope"].nunique())
        if aligned:
            print("aligned_rows=%d" % int(aligned_rows.sum()))


def validate_inputs(checksum_file, data_dir):
    with open(checksum_file) as handle:
        lines = [line.strip().split(None, 1) for line in handle if line.strip()]
    for expected, filename in lines:
        path = os.path.join(data_dir, filename)
        actual = sha256(path)
        if actual != expected:
            raise SystemExit("Input NPZ changed: %s" % filename)
        print("unchanged", filename)


def validate_ranked(hits_path, surfaces_path, pdbs_path):
    hits = pd.read_csv(hits_path, sep="\t")
    surfaces = pd.read_csv(surfaces_path, sep="\t")
    pdbs = pd.read_csv(pdbs_path, sep="\t")
    for frame, path, required in (
        (hits, hits_path, {"rank", "hit_id", "pdb_id", "surface_id", "status", "frac_geo"}),
        (surfaces, surfaces_path, {"surface_rank", "pdb_id", "surface_id", "status", "frac_geo"}),
        (pdbs, pdbs_path, {"pdb_rank", "pdb_id", "best_surface", "status", "frac_geo"}),
    ):
        missing = required.difference(frame.columns)
        if missing:
            raise SystemExit("%s missing columns %s" % (path, sorted(missing)))
        values = pd.to_numeric(frame["frac_geo"], errors="coerce")
        if len(values) and (not np.isfinite(values).all() or (values < 0).any() or (values > 1).any()):
            raise SystemExit("Invalid frac_geo in %s" % path)
        if len(values) > 1 and not np.all(values.to_numpy()[:-1] >= values.to_numpy()[1:]):
            raise SystemExit("frac_geo is not descending in %s" % path)
    if len(hits):
        expected = np.arange(1, len(hits) + 1)
        if not np.array_equal(pd.to_numeric(hits["rank"]).to_numpy(), expected):
            raise SystemExit("Hit ranks are not sequential")
        if hits["hit_id"].duplicated().any():
            raise SystemExit("Duplicate hit_id")
        root = os.path.dirname(hits_path)
        for filename in hits["hit_index_file"]:
            if not os.path.isfile(os.path.join(root, filename)):
                raise SystemExit("Missing hit index file: %s" % filename)
    if surfaces["surface_id"].duplicated().any():
        raise SystemExit("Duplicate surface_id in ranked surfaces")
    if pdbs["pdb_id"].duplicated().any():
        raise SystemExit("Duplicate pdb_id in ranked PDBs")
    print("ranked_hits=%d" % len(hits))
    print("ranked_surfaces=%d" % len(surfaces))
    print("ranked_pdbs=%d" % len(pdbs))


def main():
    mode = sys.argv[1]
    if mode == "descriptor" and len(sys.argv) == 3:
        validate_descriptor(sys.argv[2])
    elif mode == "search" and len(sys.argv) == 3:
        validate_tsv(sys.argv[2], aligned=False)
    elif mode == "align" and len(sys.argv) == 3:
        validate_tsv(sys.argv[2], aligned=True)
    elif mode == "inputs" and len(sys.argv) == 4:
        validate_inputs(sys.argv[2], sys.argv[3])
    elif mode == "ranked" and len(sys.argv) == 5:
        validate_ranked(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        raise SystemExit("Invalid validator arguments")


if __name__ == "__main__":
    main()
