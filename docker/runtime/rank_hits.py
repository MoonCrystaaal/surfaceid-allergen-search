#!/usr/bin/env python
import argparse
import ast
import csv
import os

import numpy as np
import pandas as pd


INDEX_COLUMNS = ("target_expanded_indices", "library_epitope_indices")


def read_catalog(path):
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        rows = list(reader)
    entries = []
    if {"id", "chain", "region"}.issubset(fields):
        for row in rows:
            pdb_id = row["id"].strip()
            chain = row["chain"].strip()
            surface = "%s_%s" % (pdb_id, chain)
            entries.append({
                "pdb_id": pdb_id,
                "chain": chain,
                "region": row["region"].strip().upper(),
                "surface_id": surface,
                "library_epitope": "%s.%s" % (surface, surface),
            })
    elif {"id", "Ag", "Ab"}.issubset(fields):
        for row in rows:
            pdb_id = row["id"].strip()
            ag = row["Ag"].strip()
            ab = row["Ab"].strip()
            surface = "%s_%s" % (pdb_id, ag)
            entries.append({
                "pdb_id": pdb_id,
                "chain": ag,
                "region": "C",
                "surface_id": surface,
                "library_epitope": "%s.%s_%s" % (surface, pdb_id, ab),
            })
    else:
        raise SystemExit("Catalog must contain id,chain,region or id,Ag,Ab")
    return entries


def parse_indices(value):
    if isinstance(value, np.ndarray):
        return value.astype(np.int64, copy=False)
    if isinstance(value, (list, tuple)):
        return np.asarray(value, dtype=np.int64)
    if pd.isna(value):
        return np.asarray([], dtype=np.int64)
    text = str(value).strip()
    if not text or text == "[]":
        return np.asarray([], dtype=np.int64)
    try:
        parsed = ast.literal_eval(text)
        return np.asarray(parsed, dtype=np.int64).reshape(-1)
    except (SyntaxError, ValueError):
        values = np.fromstring(text.strip("[]").replace(",", " "), sep=" ", dtype=np.int64)
        if not len(values) and text.strip("[] "):
            raise SystemExit("Cannot parse vertex indices: %s" % text[:120])
        return values


def load_descriptor_index(path):
    with np.load(path, allow_pickle=False) as data:
        labels = data["pdbs"].astype(str)
        indices = data["idxs"].astype(np.int64)
    return {
        label: indices[labels == label]
        for label in np.unique(labels)
    }


def sort_hits(frame):
    if not len(frame):
        return frame.copy()
    work = frame.copy()
    work["frac_geo"] = pd.to_numeric(work["frac_geo"], errors="raise")
    columns = ["frac_geo"]
    ascending = [False]
    if "aln1_score2" in work.columns:
        work["_aln1_score2_sort"] = pd.to_numeric(
            work["aln1_score2"], errors="coerce"
        ).fillna(np.inf)
        columns.append("_aln1_score2_sort")
        ascending.append(True)
    if "aln1_normal_score" in work.columns:
        work["_normal_sort"] = pd.to_numeric(
            work["aln1_normal_score"], errors="coerce"
        ).fillna(-np.inf)
        columns.append("_normal_sort")
        ascending.append(False)
    work = work.sort_values(columns, ascending=ascending, kind="mergesort")
    return work.drop(columns=[
        c for c in ("_aln1_score2_sort", "_normal_sort") if c in work.columns
    ])


def output_columns(frame, preferred):
    return [column for column in preferred if column in frame.columns]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-tsv", required=True)
    parser.add_argument("--aligned-tsv")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--align-top", type=int, default=0)
    parser.add_argument("--alignment-input")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    index_dir = os.path.join(args.output_dir, "hit_indices")
    os.makedirs(index_dir, exist_ok=True)
    for filename in os.listdir(index_dir):
        if filename.startswith("hit_") and filename.endswith(".npz"):
            os.remove(os.path.join(index_dir, filename))

    frame = pd.read_csv(args.input_tsv, sep="\t")
    required = {
        "target", "library epitope", "frac_geo",
        "target_expanded_indices", "library_epitope_indices",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise SystemExit("Search TSV missing columns: %s" % sorted(missing))
    frame = frame[frame["target"].astype(str) == args.target].copy()
    frame = frame[frame["library epitope"].astype(str) != args.target].copy()
    frame = sort_hits(frame).reset_index(drop=True)
    frame["_pipeline_hit_id"] = ["hit_%06d" % i for i in range(1, len(frame) + 1)]
    aligned_hit_ids = set()

    if args.alignment_input:
        selected = frame if args.align_top <= 0 else frame.head(args.align_top)
        selected.to_csv(args.alignment_input, sep="\t", index=False)

    if args.aligned_tsv:
        aligned = pd.read_csv(args.aligned_tsv, sep="\t")
        if "_pipeline_hit_id" not in aligned.columns:
            raise SystemExit("Aligned TSV lacks _pipeline_hit_id")
        aligned_hit_ids = set(aligned["_pipeline_hit_id"].astype(str))
        alignment_columns = [
            "_pipeline_hit_id", "id", "# hits repeat", "# pairs",
            "aln1_score1", "aln1_score2", "aln1_score3",
            "aln1_normal_score", "aln1_ncontact",
        ]
        alignment_columns = [c for c in alignment_columns if c in aligned.columns]
        frame = frame.drop(
            columns=[c for c in alignment_columns if c != "_pipeline_hit_id" and c in frame.columns],
            errors="ignore",
        ).merge(aligned[alignment_columns], on="_pipeline_hit_id", how="left")
        frame = sort_hits(frame).reset_index(drop=True)

    descriptor_index = load_descriptor_index(args.descriptor)
    entries = read_catalog(args.catalog)
    entry_map = {entry["library_epitope"]: entry for entry in entries}

    metadata = []
    for offset, (_, row) in enumerate(frame.iterrows(), start=1):
        hit_id = str(row["_pipeline_hit_id"])
        label = str(row["library epitope"])
        target_indices = parse_indices(row["target_expanded_indices"])
        library_local = parse_indices(row["library_epitope_indices"])
        if label not in descriptor_index:
            raise SystemExit("Descriptor lacks library entry %s" % label)
        label_mesh_indices = descriptor_index[label]
        if len(library_local) and (
            library_local.min() < 0 or library_local.max() >= len(label_mesh_indices)
        ):
            raise SystemExit("Library descriptor index is out of range for %s" % label)
        library_mesh = label_mesh_indices[library_local]
        index_filename = hit_id + ".npz"
        np.savez_compressed(
            os.path.join(index_dir, index_filename),
            target_mesh_vertex_indices=target_indices,
            library_descriptor_local_indices=library_local,
            library_mesh_vertex_indices=library_mesh,
        )
        entry = entry_map.get(label, {
            "pdb_id": label.split("_", 1)[0],
            "chain": "",
            "region": "",
            "surface_id": label.split(".", 1)[0],
        })
        if args.aligned_tsv:
            alignment_id = pd.to_numeric(pd.Series([row.get("id", np.nan)]), errors="coerce").iloc[0]
            if hit_id not in aligned_hit_ids:
                alignment_status = "not_selected"
            elif pd.notna(alignment_id) and alignment_id >= 0:
                alignment_status = "aligned"
            else:
                alignment_status = "skipped_by_surfaceid"
        else:
            alignment_status = "not_requested"
        metadata.append({
            "rank": offset,
            "hit_id": hit_id,
            "pdb_id": entry["pdb_id"],
            "chain": entry["chain"],
            "region": entry["region"],
            "surface_id": entry["surface_id"],
            "status": "hit",
            "alignment_status": alignment_status,
            "hit_index_file": "hit_indices/%s" % index_filename,
        })

    scalar = frame.drop(
        columns=list(INDEX_COLUMNS) + ["_pipeline_hit_id"], errors="ignore"
    ).reset_index(drop=True)
    meta_frame = pd.DataFrame(metadata)
    if len(scalar):
        ranked_hits = pd.concat([meta_frame, scalar], axis=1)
    else:
        ranked_hits = pd.DataFrame(columns=[
            "rank", "hit_id", "pdb_id", "chain", "region", "surface_id",
            "status", "alignment_status", "hit_index_file", "target", "library epitope", "frac_geo",
        ])
    ranked_hits_path = os.path.join(args.output_dir, args.prefix + "_ranked_hits.tsv")
    ranked_hits.to_csv(ranked_hits_path, sep="\t", index=False)

    hit_by_label = {}
    for _, row in ranked_hits.iterrows():
        hit_by_label.setdefault(str(row["library epitope"]), row)

    surface_rows = []
    scalar_names = [
        "frac_geo", "frac_expanded", "frac_library_hits", "target_nhits",
        "target_nexpanded", "library_nhits", "library_nexpanded", "mean_desc_dist",
        "aln1_score1", "aln1_score2", "aln1_score3", "aln1_normal_score",
        "aln1_ncontact",
    ]
    for entry in entries:
        if entry["library_epitope"] == args.target:
            continue
        best = hit_by_label.get(entry["library_epitope"])
        row = dict(entry)
        if best is None:
            row.update({
                "best_hit_id": "", "status": "no_retained_hit",
                "alignment_status": "not_applicable", "frac_geo": 0.0,
            })
        else:
            row.update({
                "best_hit_id": best["hit_id"], "status": "hit",
                "alignment_status": best["alignment_status"],
            })
            for column in scalar_names:
                if column in best.index:
                    row[column] = best[column]
        surface_rows.append(row)

    surfaces = pd.DataFrame(surface_rows)
    if len(surfaces):
        surfaces["frac_geo"] = pd.to_numeric(surfaces["frac_geo"], errors="coerce").fillna(0.0)
        surfaces = surfaces.sort_values(
            ["frac_geo", "pdb_id", "surface_id"],
            ascending=[False, True, True],
            kind="mergesort",
        ).reset_index(drop=True)
        surfaces.insert(0, "surface_rank", np.arange(1, len(surfaces) + 1))
    surface_path = os.path.join(args.output_dir, args.prefix + "_ranked_surfaces.tsv")
    surfaces.to_csv(surface_path, sep="\t", index=False)

    pdb_rows = []
    if len(surfaces):
        for pdb_id, group in surfaces.groupby("pdb_id", sort=False):
            best = group.iloc[0]
            row = {
                "pdb_id": pdb_id,
                "best_surface": best["surface_id"],
                "best_hit_id": best["best_hit_id"],
                "status": best["status"],
                "alignment_status": best["alignment_status"],
                "frac_geo": best["frac_geo"],
            }
            for column in scalar_names[1:]:
                if column in best.index:
                    row[column] = best[column]
            pdb_rows.append(row)
    pdbs = pd.DataFrame(pdb_rows)
    if len(pdbs):
        pdbs = pdbs.sort_values(
            ["frac_geo", "pdb_id"], ascending=[False, True], kind="mergesort"
        ).reset_index(drop=True)
        pdbs.insert(0, "pdb_rank", np.arange(1, len(pdbs) + 1))
    pdb_path = os.path.join(args.output_dir, args.prefix + "_ranked_pdbs.tsv")
    pdbs.to_csv(pdb_path, sep="\t", index=False)

    print("ranked_hits=%d" % len(ranked_hits))
    print("ranked_surfaces=%d" % len(surfaces))
    print("ranked_pdbs=%d" % len(pdbs))
    print("output_dir=%s" % args.output_dir)


if __name__ == "__main__":
    main()
