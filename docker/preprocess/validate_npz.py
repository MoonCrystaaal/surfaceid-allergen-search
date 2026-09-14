#!/usr/bin/env python
import csv
import os
import sys

import numpy as np


REQUIRED_KEYS = {
    "face",
    "pos",
    "normals",
    "edge_index",
    "x_local",
    "x_initial",
    "rho",
    "theta",
    "mask",
    "list_indices",
    "iface",
}


def validate(path):
    with np.load(path, allow_pickle=False) as data:
        missing = REQUIRED_KEYS.difference(data.files)
        if missing:
            raise ValueError("missing keys: %s" % sorted(missing))
        pos = data["pos"]
        normals = data["normals"]
        x_initial = data["x_initial"]
        x_local = data["x_local"]
        rho = data["rho"]
        theta = data["theta"]
        mask = data["mask"]
        edge_index = data["edge_index"]
        list_indices = data["list_indices"]
        if x_initial.ndim != 2 or x_initial.shape[1] != 5:
            raise ValueError("x_initial must have shape (N, 5)")
        if list_indices.ndim != 2 or list_indices.shape[1] != 200:
            raise ValueError("list_indices must have shape (N, 200)")
        patch_arrays = {
            "x_local": x_local,
            "rho": rho,
            "theta": theta,
            "mask": mask,
            "list_indices": list_indices,
        }
        for key, value in patch_arrays.items():
            if value.shape[0] != len(pos) or value.shape[1] != 200:
                raise ValueError("%s must be vertex-aligned with patch width 200; got %s" %
                                 (key, value.shape))
        if len(pos) != len(normals) or len(pos) != len(x_initial):
            raise ValueError("vertex-aligned arrays have inconsistent lengths")
        if edge_index.ndim != 2 or edge_index.shape[0] != 2:
            raise ValueError("edge_index must have shape (2, E)")
        for key in REQUIRED_KEYS.difference({"list_indices"}):
            value = data[key]
            if np.issubdtype(value.dtype, np.number) and not np.isfinite(value).all():
                raise ValueError("%s contains NaN or Inf" % key)
        valid_indices = list_indices[list_indices >= 0]
        if valid_indices.size and valid_indices.max() >= len(pos):
            raise ValueError("list_indices contains an out-of-range vertex")
        if edge_index.size and (edge_index.min() < 0 or edge_index.max() >= len(pos)):
            raise ValueError("edge_index contains an out-of-range vertex")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: validate_npz.py NPZ_DIR CONVERTER_CSV")
    npz_dir, manifest = sys.argv[1:]
    with open(manifest, newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        filename = "%s_%s_surface.npz" % (row["id"], row["chain"])
        path = os.path.join(npz_dir, filename)
        if not os.path.isfile(path):
            raise SystemExit("missing output: %s" % path)
        validate(path)
        print("OK", filename)


if __name__ == "__main__":
    main()
