#!/usr/bin/env python
import hashlib
import os
import sys

import Bio
import matplotlib
import numpy as np
import pandas
import plyfile
import scipy
import seaborn
import sklearn
import torch
import torch_scatter
import yaml

sys.path.insert(0, "/opt/surfaceid")
from src.model.model import Model


MODEL_PATH = "/opt/surfaceid/models/model_final_002.pth"
MODEL_SHA256 = "63f6394df85f3b833e97e50a2e8a30c5eba702c4a146d11a0c4d2ca2690c91b1"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    print("Python:", sys.version.split()[0])
    print("PyTorch:", torch.__version__)
    print("CUDA build:", torch.version.cuda)
    print("CUDA available:", torch.cuda.is_available())
    print("torch_scatter:", getattr(torch_scatter, "__version__", "unknown"))
    print("NumPy:", np.__version__)
    print("pandas:", pandas.__version__)
    print("SciPy:", scipy.__version__)
    print("scikit-learn:", sklearn.__version__)
    print("BioPython:", Bio.__version__)
    print("matplotlib:", matplotlib.__version__)
    print("seaborn:", seaborn.__version__)
    print("PyYAML:", yaml.__version__)
    print("plyfile:", getattr(plyfile, "__version__", "installed"))
    actual_hash = sha256(MODEL_PATH)
    if actual_hash != MODEL_SHA256:
        raise SystemExit("Model checksum mismatch")
    print("Model SHA-256:", actual_hash)
    params = dict(
        rho_max=6.0, nbins_rho=5, nbins_theta=16, num_in=5,
        neg_margin=10.0, add_center_pixel=True,
        share_soft_grid_across_channel=True, conv_type="sep",
        num_filters=512, weight_decay=1.0e-2, dropout=0.1,
        min_sig=5.0e-2, lr=5.0e-4,
    )
    model = Model(**params)
    model.load_state_dict(torch.load(MODEL_PATH, map_location=torch.device("cpu")))
    model.eval()
    model.dthetas = model.dthetas.to("cpu")
    with torch.no_grad():
        x = torch.zeros((2, 20, 5), dtype=torch.float32)
        rho = torch.linspace(0.0, 6.0, 20).repeat(2, 1)
        theta = torch.linspace(0.0, 6.0, 20).repeat(2, 1)
        mask = torch.ones((2, 20), dtype=torch.float32)
        output, _, _, _ = model(x, rho, theta, mask, calc_loss=False)
    if output.shape != (2, 512) or not torch.isfinite(output).all():
        raise SystemExit("Unexpected model output: %r" % (tuple(output.shape),))
    print("Model output shape:", tuple(output.shape))


if __name__ == "__main__":
    main()
