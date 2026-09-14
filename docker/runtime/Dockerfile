ARG PYTHON_IMAGE=python@sha256:1326d0fd281d283b077fd249e618339a44c9ca5aae6e05cb4f069a087e827922
FROM ${PYTHON_IMAGE}

ARG SURFACEID_COMMIT=bc0d0148dfa0c34ec238b6a746902dff2198410d

LABEL org.opencontainers.image.title="SurfaceID CPU runtime"
LABEL org.opencontainers.image.description="CPU-only SurfaceID descriptor, search, and alignment runtime"
LABEL org.opencontainers.image.source="https://github.com/Sanofi-Public/LMR-SurfaceID"
LABEL org.opencontainers.image.revision="${SURFACEID_COMMIT}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    OMP_NUM_THREADS=12 \
    MKL_NUM_THREADS=12 \
    OPENBLAS_NUM_THREADS=12

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip==23.3.2 setuptools==69.0.3 wheel==0.42.0 \
    && python -m pip install --no-cache-dir \
         --index-url https://download.pytorch.org/whl/cpu \
         torch==2.0.0 \
    && python -m pip install --no-cache-dir \
         --find-links https://data.pyg.org/whl/torch-2.0.0+cpu.html \
         torch_scatter==2.1.1+pt20cpu \
    && python -m pip install --no-cache-dir \
         adabelief_pytorch==0.2.1 \
         Bio==1.5.9 \
         biopython==1.81 \
         matplotlib==3.6.2 \
         numpy==1.23.5 \
         pandas==1.5.2 \
         PyYAML==6.0 \
         scikit_learn==1.2.2 \
         scipy==1.10.1 \
         seaborn==0.12.2 \
         plyfile==0.9

WORKDIR /opt/surfaceid

COPY source/LMR-SurfaceID/main.py /opt/surfaceid/main.py
COPY source/LMR-SurfaceID/src /opt/surfaceid/src
COPY source/LMR-SurfaceID/models/model_final_002.pth /opt/surfaceid/models/model_final_002.pth
COPY source/LMR-SurfaceID/test/input.csv /opt/surfaceid/test/input.csv

# The upstream search/align path uses attribute access on numpy.lib.npyio.NpzFile,
# which only supports mapping access for these arrays.
RUN python - <<'PY'
path = "/opt/surfaceid/main.py"
replacements = {
    "pdbs = data.pdbs": 'pdbs = data["pdbs"]',
    "x_desc = data.x": 'x_desc = data["x"]',
}
with open(path, "r") as handle:
    text = handle.read()
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit("Unexpected SurfaceID NPZ access: " + old)
    text = text.replace(old, new)
with open(path, "w") as handle:
    handle.write(text)
PY

COPY docker/runtime/prepare_runtime.py /opt/runtime/prepare_runtime.py
COPY docker/runtime/prepare_query_region.py /opt/runtime/prepare_query_region.py
COPY docker/runtime/rank_hits.py /opt/runtime/rank_hits.py
COPY docker/runtime/validate_runtime.py /opt/runtime/validate_runtime.py
COPY docker/runtime/runtime_check.py /opt/runtime/runtime_check.py
COPY docker/runtime/runtime.sh /usr/local/bin/surfaceid-runtime

RUN chmod 0555 /opt/runtime/*.py /usr/local/bin/surfaceid-runtime \
    && printf '%s  %s\n' \
         '63f6394df85f3b833e97e50a2e8a30c5eba702c4a146d11a0c4d2ca2690c91b1' \
         '/opt/surfaceid/models/model_final_002.pth' \
         >/opt/surfaceid/models/model_final_002.pth.sha256 \
    && sha256sum -c /opt/surfaceid/models/model_final_002.pth.sha256

ENTRYPOINT ["/usr/local/bin/surfaceid-runtime"]
CMD ["--help"]
