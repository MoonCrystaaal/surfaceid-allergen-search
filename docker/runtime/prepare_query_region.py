#!/usr/bin/env python
import argparse
import os

import numpy as np
from scipy.spatial import cKDTree


def expand_vertices(seed, rho, list_indices, radius):
    if not len(seed):
        return np.asarray([], dtype=np.int32)
    selected_rho = rho[seed]
    expanded = list_indices[seed][(selected_rho > 0) & (selected_rho < radius)]
    return np.unique(expanded).astype(np.int32)


def whole_vertices(rho, list_indices):
    vertices = list_indices[(rho > 0)]
    return np.unique(vertices).astype(np.int32)


def restricted_vertices(pos, rho, list_indices, xyz, cutoff, expand_radius):
    if xyz.ndim == 1:
        xyz = xyz.reshape(1, -1)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not len(xyz):
        raise SystemExit("XYZ file must contain one or more rows with three coordinates")
    if not np.isfinite(xyz).all():
        raise SystemExit("XYZ file contains NaN or Inf")
    distances, _ = cKDTree(xyz).query(pos, k=1)
    seed = np.where(distances < cutoff)[0]
    return seed, expand_vertices(seed, rho, list_indices, expand_radius)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface-npz", required=True)
    parser.add_argument("--surface-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--scope", choices=("full", "restricted"), required=True)
    parser.add_argument("--xyz")
    parser.add_argument("--cutoff", type=float, default=3.0)
    parser.add_argument("--expand-radius", type=float, default=2.0)
    args = parser.parse_args()

    with np.load(args.surface_npz, allow_pickle=False) as data:
        pos = data["pos"]
        rho = data["rho"]
        list_indices = data["list_indices"]

    if args.scope == "full":
        seed_count = len(pos)
        selected = whole_vertices(rho, list_indices)
    else:
        if not args.xyz:
            raise SystemExit("--xyz is required for restricted query scope")
        xyz = np.loadtxt(args.xyz, dtype=np.float64)
        seed, selected = restricted_vertices(
            pos, rho, list_indices, xyz, args.cutoff, args.expand_radius
        )
        seed_count = len(seed)

    if not len(selected):
        raise SystemExit("Query region contains no surface vertices")

    os.makedirs(args.output_dir, exist_ok=True)
    output = os.path.join(
        args.output_dir,
        "%s_contacts.%s.npy" % (args.surface_id, args.surface_id),
    )
    np.save(output, selected)
    print("scope=%s" % args.scope)
    print("surface_vertices=%d" % len(pos))
    print("seed_vertices=%d" % seed_count)
    print("selected_vertices=%d" % len(selected))
    print("output=%s" % output)


if __name__ == "__main__":
    main()
