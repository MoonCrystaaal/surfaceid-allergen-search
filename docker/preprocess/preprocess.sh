#!/usr/bin/env bash
set -Eeuo pipefail

readonly MASIF_SITE_DIR="/masif/data/masif_site"
readonly MASIF_DATA_DIR="${MASIF_SITE_DIR}/data_preparation"
readonly SURFACEID_DIR="/opt/surfaceid"
readonly DEFAULT_INPUT_DIR="/input"
readonly DEFAULT_WORK_DIR="/work"

OUTPUT_UID="${OUTPUT_UID:-1026}"
OUTPUT_GID="${OUTPUT_GID:-1026}"

usage() {
  cat <<'EOF'
Usage:
  surfaceid-preprocess --check
  surfaceid-preprocess --manifest /input/structures.csv [--input-dir /input] [--work-dir /work]

Manifest columns:
  id,chain,file

Example:
  4FQI,AB,4FQI.pdb
  4FQI,HL,4FQI.pdb

The work directory must be a dedicated per-run bind mount. Results are written
to its masif-data, npz, logs, and manifest subdirectories. At exit, only these
subdirectories are changed to OUTPUT_UID:OUTPUT_GID (default 1026:1026).
EOF
}

check_environment() {
  local failed=0
  printf 'MaSIF commit: '
  git -C /masif rev-parse HEAD
  printf 'Python: '
  python --version
  python - <<'PY'
import pymesh
import Bio
import numpy
import pandas

print("NumPy:", numpy.__version__)
print("pandas:", pandas.__version__)
print("PyMesh:", getattr(pymesh, "__version__", "unknown"))
print("BioPython:", Bio.__version__)
PY

  for path in \
    "${MSMS_BIN:-}" \
    "${APBS_BIN:-}" \
    "${MULTIVALUE_BIN:-}" \
    "${PDB2PQR_BIN:-}" \
    /usr/local/bin/reduce \
    "${SURFACEID_DIR}/masif2npz.py" \
    "${SURFACEID_DIR}/validate_npz.py"; do
    if [[ -n "${path}" && -r "${path}" ]]; then
      printf 'OK %s\n' "${path}"
    else
      printf 'MISSING %s\n' "${path:-<unset>}" >&2
      failed=1
    fi
  done
  python - "${SURFACEID_DIR}/masif2npz.py" "${SURFACEID_DIR}/validate_npz.py" <<'PY'
import sys
for path in sys.argv[1:]:
    with open(path, "rb") as handle:
        compile(handle.read(), path, "exec")
    print("Syntax OK:", path)
PY
  return "${failed}"
}

safe_chown_outputs() {
  local work_dir="$1"
  local path
  for path in masif-data npz logs manifest; do
    if [[ -d "${work_dir}/${path}" ]]; then
      chown -R "${OUTPUT_UID}:${OUTPUT_GID}" "${work_dir}/${path}" || true
    fi
  done
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" || $# -eq 0 ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--check" ]]; then
  check_environment
  exit 0
fi

manifest=""
input_dir="${DEFAULT_INPUT_DIR}"
work_dir="${DEFAULT_WORK_DIR}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --manifest)
      manifest="${2:?--manifest requires a path}"
      shift 2
      ;;
    --input-dir)
      input_dir="${2:?--input-dir requires a path}"
      shift 2
      ;;
    --work-dir)
      work_dir="${2:?--work-dir requires a path}"
      shift 2
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

[[ -n "${manifest}" ]] || { echo '--manifest is required' >&2; exit 2; }
[[ -f "${manifest}" ]] || { echo "Manifest not found: ${manifest}" >&2; exit 2; }
[[ -d "${input_dir}" ]] || { echo "Input directory not found: ${input_dir}" >&2; exit 2; }
[[ -d "${work_dir}" ]] || { echo "Work directory must be a bind mount: ${work_dir}" >&2; exit 2; }

mkdir -p \
  "${work_dir}/masif-data" \
  "${work_dir}/npz" \
  "${work_dir}/logs" \
  "${work_dir}/manifest"

trap 'safe_chown_outputs "${work_dir}"' EXIT

# MaSIF writes to this fixed path. The caller bind-mounts the per-run
# masif-data directory here, keeping persistent data outside the container.
if [[ "$(stat -c '%d:%i' "${MASIF_DATA_DIR}")" != "$(stat -c '%d:%i' "${work_dir}/masif-data")" ]]; then
  echo "Expected ${MASIF_DATA_DIR} and ${work_dir}/masif-data to be the same bind-mounted directory." >&2
  exit 2
fi

check_environment >"${work_dir}/logs/environment.log" 2>&1

normalized_manifest="${work_dir}/manifest/structures.csv"
cp "${manifest}" "${normalized_manifest}"

rows_file="$(mktemp)"
converter_csv="$(mktemp)"
staging_dir="$(mktemp -d)"
trap 'rm -f "${rows_file}" "${converter_csv}"; rm -rf "${staging_dir}"; safe_chown_outputs "${work_dir}"' EXIT

python - "${manifest}" "${rows_file}" "${converter_csv}" <<'PY'
import csv
import re
import sys

source, rows_path, converter_path = sys.argv[1:]
required = {"id", "chain", "file"}
rows = []
with open(source, newline="") as handle:
    reader = csv.DictReader(handle)
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise SystemExit("Manifest must contain id,chain,file columns")
    for line_number, row in enumerate(reader, start=2):
        pdb_id = row["id"].strip()
        chain = row["chain"].strip()
        filename = row["file"].strip()
        if not re.fullmatch(r"[A-Za-z0-9.-]+", pdb_id):
            raise SystemExit("Invalid id on line %d" % line_number)
        if not re.fullmatch(r"[A-Za-z0-9]+", chain):
            raise SystemExit("Invalid chain on line %d" % line_number)
        if not filename or filename != filename.split("/")[-1]:
            raise SystemExit("file must be a basename on line %d" % line_number)
        rows.append((pdb_id, chain, filename))
if not rows:
    raise SystemExit("Manifest contains no structures")
if len({(p, c) for p, c, _ in rows}) != len(rows):
    raise SystemExit("Manifest contains duplicate id,chain rows")
with open(rows_path, "w", newline="") as handle:
    for row in rows:
        handle.write("\t".join(row) + "\n")
with open(converter_path, "w", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(["id", "chain"])
    for pdb_id, chain, _ in rows:
        writer.writerow([pdb_id, chain])
PY

mkdir -p "${staging_dir}/plys"

while IFS=$'\t' read -r pdb_id chain filename; do
  input_file="${input_dir}/${filename}"
  surface_id="${pdb_id}_${chain}"
  [[ -f "${input_file}" ]] || { echo "Input PDB not found: ${input_file}" >&2; exit 2; }

  (
    cd "${MASIF_SITE_DIR}"
    ./data_prepare_one.sh --file "${input_file}" "${surface_id}"
  ) 2>&1 | tee "${work_dir}/logs/${surface_id}.log"

  ply_file="${MASIF_DATA_DIR}/01-benchmark_surfaces/${surface_id}.ply"
  precomp_dir="${MASIF_DATA_DIR}/04a-precomputation_9A/precomputation/${surface_id}"
  [[ -f "${ply_file}" ]] || { echo "Missing MaSIF PLY: ${ply_file}" >&2; exit 1; }
  [[ -d "${precomp_dir}" ]] || { echo "Missing MaSIF precomputation: ${precomp_dir}" >&2; exit 1; }

  ln -s "${ply_file}" "${staging_dir}/plys/${surface_id}.ply"
  ln -s "${precomp_dir}" "${staging_dir}/${surface_id}"
done <"${rows_file}"

python "${SURFACEID_DIR}/masif2npz.py" \
  "${staging_dir}" \
  "${work_dir}/npz" \
  "${converter_csv}" 2>&1 | tee "${work_dir}/logs/masif2npz.log"

python "${SURFACEID_DIR}/validate_npz.py" \
  "${work_dir}/npz" \
  "${converter_csv}" 2>&1 | tee "${work_dir}/logs/validate_npz.log"

python - <<'PY' >"${work_dir}/manifest/versions.txt"
import pymesh
import Bio
import numpy
import pandas
print("numpy=" + numpy.__version__)
print("pandas=" + pandas.__version__)
print("pymesh=" + getattr(pymesh, "__version__", "unknown"))
print("biopython=" + Bio.__version__)
PY
git -C /masif rev-parse HEAD >>"${work_dir}/manifest/versions.txt"

echo "SurfaceID preprocessing completed: ${work_dir}/npz"
