#!/usr/bin/env python
import argparse
import csv
import hashlib
import os
import re
import shutil
import subprocess

import numpy as np
import yaml


REQUIRED_NPZ_KEYS = {
    "face", "pos", "normals", "edge_index", "x_local", "x_initial",
    "rho", "theta", "mask", "list_indices", "iface",
}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_id(value, label, number):
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9.-]+", value):
        raise SystemExit("Invalid %s on CSV line %d" % (label, number))
    return value


def valid_chain(value, label, number):
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", value):
        raise SystemExit("Invalid %s on CSV line %d" % (label, number))
    return value


def read_catalog(path, scope):
    with open(path, newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if scope == "contact":
            required = {"id", "Ag", "Ab"}
        else:
            required = {"id", "chain", "region"}
        if not required.issubset(fields):
            raise SystemExit(
                "%s catalog must contain %s columns" %
                (scope, ",".join(sorted(required)))
            )

        rows = []
        for number, row in enumerate(reader, start=2):
            pdb_id = valid_id(row["id"], "id", number)
            if scope == "contact":
                ag = valid_chain(row["Ag"], "Ag", number)
                ab = valid_chain(row["Ab"], "Ab", number)
                rows.append({"id": pdb_id, "Ag": ag, "Ab": ab})
            else:
                chain = valid_chain(row["chain"], "chain", number)
                region = row["region"].strip().upper()
                if region != "F":
                    raise SystemExit(
                        "Library catalog line %d must use region F; query restriction is supplied separately"
                        % number
                    )
                rows.append({"id": pdb_id, "chain": chain, "region": region})
    if not rows:
        raise SystemExit("Input catalog contains no entries")

    if scope == "contact":
        keys = [(row["id"], row["Ag"], row["Ab"]) for row in rows]
    else:
        keys = [(row["id"], row["chain"]) for row in rows]
    if len(keys) != len(set(keys)):
        raise SystemExit("Input catalog contains duplicate entries")
    return rows


def catalog_surfaces(rows, scope):
    if scope == "contact":
        return sorted({
            "%s_%s" % (row["id"], chain)
            for row in rows for chain in (row["Ag"], row["Ab"])
        })
    return sorted({"%s_%s" % (row["id"], row["chain"]) for row in rows})


def validate_npz(path):
    with np.load(path, allow_pickle=False) as data:
        missing = REQUIRED_NPZ_KEYS.difference(data.files)
        if missing:
            raise SystemExit("%s missing keys %s" % (path, sorted(missing)))
        if data["x_initial"].ndim != 2 or data["x_initial"].shape[1] != 5:
            raise SystemExit("%s has invalid x_initial shape" % path)
        if data["list_indices"].ndim != 2 or data["list_indices"].shape[1] != 200:
            raise SystemExit("%s has invalid list_indices shape" % path)
        vertex_count = len(data["pos"])
        for key in ("x_local", "rho", "theta", "mask", "list_indices"):
            value = data[key]
            if value.shape[0] != vertex_count or value.shape[1] != 200:
                raise SystemExit(
                    "%s has incompatible %s shape %r; SurfaceID requires patch width 200"
                    % (path, key, value.shape)
                )


def install_file(source, target, checksum_lines):
    if not os.path.isfile(source):
        raise SystemExit("Missing input file: %s" % source)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    subprocess.run(
        ["cp", "--reflink=auto", "--preserve=mode,timestamps", source, target],
        check=True,
    )
    source_hash = sha256(source)
    if sha256(target) != source_hash:
        raise SystemExit("Checksum mismatch after copy: %s" % os.path.basename(source))
    checksum_lines.append("%s  %s\n" % (source_hash, os.path.basename(target)))


def make_config(work_dir, input_csv, case_name, stage, scope, target):
    enabled = {
        "desc": (True, False, False),
        "search": (False, True, False),
        "align": (False, False, True),
    }[stage]
    desc, search, align = enabled
    return {
        "CONTACT": scope == "contact",
        "DESC": desc,
        "SEARCH": search,
        # A reusable library already contains descriptors and the full-surface
        # contacts/within arrays.  Search must consume those files, not rebuild
        # them on every query.
        "REUSE_PRECOMPUTED": search and scope == "full",
        "RESTRICT": False,
        "ALIGN": align,
        "SAVEPLY": False,
        "HEATMAP": False,
        "MODEL": {"NAME": "final_002"},
        "MODEL_PARAMETER": {
            "rho_max": 6.0,
            "nbins_rho": 5,
            "nbins_theta": 16,
            "num_in": 5,
            "neg_margin": 10.0,
            "add_center_pixel": True,
            "share_soft_grid_across_channel": True,
            "conv_type": "sep",
            "num_filters": 512,
            "weight_decay": 1.0e-2,
            "dropout": 0.1,
            "min_sig": 5.0e-2,
            "lr": 5.0e-4,
        },
        "SPATIAL_PARAMETER": {
            "thres": 5.0,
            "expand_radius": 2.0,
            "neighbor_dist": 3.0,
            "nmin_pts": 40,
            "nmin_pts_library": 30,
            "contact_thres1": 3.0,
            "contact_thres2": None,
            "contact_mode": "dist",
            "npatience": 100,
        },
        "PATH": {
            "CATALOG_PAIRS": input_csv,
            "OUTDIR": os.path.join(work_dir, "data"),
            "SAVEDIR": "/opt/surfaceid/models",
            "MODEL": "final_002",
            "TARGET": target,
            "CASE": case_name,
        },
        "HIT_COLUMNS": [
            "target", "library epitope", "target_nhits", "target_nexpanded",
            "mean_desc_dist", "library_nhits", "library_nexpanded",
            "frac_library_hits", "target_expanded_indices",
            "library_epitope_indices",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--input-npz-dir")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--scope", choices=("contact", "full", "restricted"), default="contact")
    parser.add_argument("--target")
    parser.add_argument("--query-npz")
    parser.add_argument("--library-descriptor")
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.case):
        raise SystemExit("Invalid case name")
    if args.target and not re.fullmatch(r"[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+", args.target):
        raise SystemExit("Target must have surface.region form")

    catalog_scope = "contact" if args.scope == "contact" else "full"
    rows = read_catalog(args.input_csv, catalog_scope)
    work_dir = os.path.abspath(args.work_dir)
    config_dir = os.path.join(work_dir, "config")
    data_dir = os.path.join(work_dir, "data")
    descriptor_dir = os.path.join(work_dir, "descriptors")
    manifest_dir = os.path.join(work_dir, "manifest")
    for directory in (config_dir, data_dir, descriptor_dir, manifest_dir):
        os.makedirs(directory, exist_ok=True)

    copied_csv = os.path.join(config_dir, "input.csv")
    shutil.copy2(args.input_csv, copied_csv)

    if args.initialize:
        if not args.input_npz_dir:
            raise SystemExit("--input-npz-dir is required with --initialize")
        descriptor = os.path.join(descriptor_dir, "nn_desc.%s.npz" % args.case)
        if os.path.exists(descriptor):
            raise SystemExit("Runtime directory already contains a descriptor; refusing to overwrite")

        checksum_lines = []
        copied_names = set()
        for surface in catalog_surfaces(rows, catalog_scope):
            filename = surface + "_surface.npz"
            source = os.path.join(args.input_npz_dir, filename)
            target = os.path.join(data_dir, filename)
            validate_npz(source)
            install_file(source, target, checksum_lines)
            copied_names.add(filename)

        if args.query_npz:
            filename = os.path.basename(args.query_npz)
            if not re.fullmatch(r"[A-Za-z0-9_.-]+_surface\.npz", filename):
                raise SystemExit("Query NPZ must be named <surface>_surface.npz")
            validate_npz(args.query_npz)
            if filename not in copied_names:
                install_file(args.query_npz, os.path.join(data_dir, filename), checksum_lines)

        if args.library_descriptor:
            descriptor_checksums = []
            install_file(args.library_descriptor, descriptor, descriptor_checksums)
            with open(os.path.join(manifest_dir, "library-descriptor.sha256"), "w") as handle:
                handle.writelines(descriptor_checksums)

        with open(os.path.join(manifest_dir, "input-checksums.sha256"), "w") as handle:
            handle.writelines(checksum_lines)

    for stage in ("desc", "search", "align"):
        config = make_config(
            work_dir, copied_csv, args.case, stage, catalog_scope, args.target
        )
        with open(os.path.join(config_dir, stage + ".yml"), "w") as handle:
            yaml.safe_dump(config, handle, sort_keys=False)

    run_parameters = {
        "case": args.case,
        "scope": args.scope,
        "target": args.target,
        "reuse_precomputed": args.scope == "full",
        "query_descriptor_recomputed": False if args.scope == "full" else None,
        "contacts_within_recomputed": False if args.scope == "full" else None,
        "catalog": os.path.basename(args.input_csv),
        "query_npz": os.path.basename(args.query_npz) if args.query_npz else None,
        "library_descriptor": (
            os.path.basename(args.library_descriptor) if args.library_descriptor else None
        ),
    }
    with open(os.path.join(manifest_dir, "parameters.yml"), "w") as handle:
        yaml.safe_dump(run_parameters, handle, sort_keys=False)


if __name__ == "__main__":
    main()
