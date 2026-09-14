ARG MASIF_IMAGE=pablogainza/masif@sha256:4e1abc4914e3894e949f81bda204c35525fc3a91da3f0d71dcf91899eee16173
FROM ${MASIF_IMAGE}

ARG SURFACEID_COMMIT=bc0d0148dfa0c34ec238b6a746902dff2198410d

LABEL org.opencontainers.image.title="SurfaceID preprocessing"
LABEL org.opencontainers.image.description="MaSIF preprocessing and conversion to SurfaceID NPZ"
LABEL org.opencontainers.image.source="https://github.com/Sanofi-Public/LMR-SurfaceID"
LABEL org.opencontainers.image.revision="${SURFACEID_COMMIT}"

# Keep the legacy MaSIF NumPy/PyMesh stack intact while adding the one
# dependency required by SurfaceID's official masif2npz.py converter.
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
      python-dateutil==2.8.1 \
      pytz==2019.3 \
      pandas==0.25.3

# SurfaceID's model and official masif2npz converter use 200 vertices per
# geodesic patch.  The MaSIF site default is 100, so make the documented
# SurfaceID-specific preprocessing modification explicit and reproducible.
RUN python - <<'PY'
path = "/masif/source/default_config/masif_opts.py"
old = 'masif_opts["site"]["max_shape_size"] = 100'
new = 'masif_opts["site"]["max_shape_size"] = 200'
with open(path, "r") as handle:
    text = handle.read()
if text.count(old) != 1:
    raise SystemExit("Unexpected MaSIF site max_shape_size definition")
with open(path, "w") as handle:
    handle.write(text.replace(old, new))
PY

COPY source/LMR-SurfaceID/src/masif2npz.py /opt/surfaceid/masif2npz.py
COPY docker/preprocess/validate_npz.py /opt/surfaceid/validate_npz.py
COPY docker/preprocess/preprocess.sh /usr/local/bin/surfaceid-preprocess

RUN chmod 0555 \
      /opt/surfaceid/masif2npz.py \
      /opt/surfaceid/validate_npz.py \
      /usr/local/bin/surfaceid-preprocess

ENTRYPOINT ["/usr/local/bin/surfaceid-preprocess"]
CMD ["--help"]
