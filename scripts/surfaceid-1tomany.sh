#!/usr/bin/env bash
set -Eeuo pipefail

readonly PREPROCESS_IMAGE="surfaceid-preprocess:0.2"
readonly RUNTIME_IMAGE="surfaceid-runtime:0.5"
readonly QUERY_CPUS=10

usage() {
  cat <<'EOF'
Usage:
  surfaceid-1tomany build-library \
    --name LIBRARY_NAME \
    --pdb-dir /path/under/DB_PATH \
    --structures /path/under/DB_PATH/structures.csv \
    --catalog /path/under/DB_PATH/library.csv

  surfaceid-1tomany query \
    --library LIBRARY_NAME \
    --query-id QUERY_ID \
    --query-chain A

Library structures.csv columns: id,chain,file
Library catalog.csv columns: id,chain,region (region must be F)
EOF
}

fail() {
  echo "$*" >&2
  exit 2
}

require_identifier() {
  local value="$1"
  local label="$2"
  [[ "${value}" =~ ^[A-Za-z0-9_.-]+$ ]] || fail "Invalid ${label}: ${value}"
}

require_chain() {
  local value="$1"
  [[ "${value}" =~ ^[A-Za-z0-9]+$ ]] || fail "Invalid chain/group: ${value}"
}

resolve_under_db() {
  local value="$1"
  local resolved
  resolved="$(realpath -e "${value}")" || fail "Path not found: ${value}"
  case "${resolved}" in
    "${db_root}"/*) printf '%s\n' "${resolved}" ;;
    *) fail "Path must be below DB_PATH (${db_root}): ${resolved}" ;;
  esac
}

[[ $# -gt 0 ]] || { usage; exit 2; }
if [[ "${1}" == "--help" || "${1}" == "-h" ]]; then
  usage
  exit 0
fi
[[ -n "${DB_PATH:-}" ]] || fail 'DB_PATH is not set'
db_root="$(realpath -e "${DB_PATH}")"
project_root="${db_root}/surfaceid-project"
[[ -d "${project_root}" ]] || fail "Project directory not found: ${project_root}"

command="$1"
shift

if [[ "${command}" == "build-library" ]]; then
  library_name=""
  pdb_dir=""
  structures=""
  catalog=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --name) library_name="${2:?--name requires a value}"; shift 2 ;;
      --pdb-dir) pdb_dir="${2:?--pdb-dir requires a value}"; shift 2 ;;
      --structures) structures="${2:?--structures requires a value}"; shift 2 ;;
      --catalog) catalog="${2:?--catalog requires a value}"; shift 2 ;;
      --help|-h) usage; exit 0 ;;
      *) fail "Unknown argument: $1" ;;
    esac
  done
  require_identifier "${library_name}" "library name"
  pdb_dir="$(resolve_under_db "${pdb_dir}")"
  structures="$(resolve_under_db "${structures}")"
  catalog="$(resolve_under_db "${catalog}")"
  [[ -d "${pdb_dir}" ]] || fail "PDB directory not found: ${pdb_dir}"

  library_root="${project_root}/work/libraries/${library_name}"
  [[ ! -e "${library_root}" ]] || fail "Library already exists: ${library_root}"
  preprocess_root="${library_root}/preprocess"
  runtime_root="${library_root}/runtime"
  mkdir -p "${library_root}/input" "${preprocess_root}/masif-data" "${runtime_root}"
  cp --preserve=mode,timestamps "${structures}" "${library_root}/input/structures.csv"
  cp --preserve=mode,timestamps "${catalog}" "${library_root}/input/library.csv"

  docker run --rm \
    -v "${pdb_dir}:/input:ro" \
    -v "${library_root}/input/structures.csv:/manifest/structures.csv:ro" \
    -v "${preprocess_root}/masif-data:/masif/data/masif_site/data_preparation" \
    -v "${preprocess_root}:/work" \
    "${PREPROCESS_IMAGE}" \
    --manifest /manifest/structures.csv --input-dir /input --work-dir /work

  docker run --rm \
    -v "${preprocess_root}/npz:/input/npz:ro" \
    -v "${library_root}/input/library.csv:/input/library.csv:ro" \
    -v "${runtime_root}:/work" \
    "${RUNTIME_IMAGE}" \
    --mode desc --scope full \
    --input-npz-dir /input/npz --input-csv /input/library.csv \
    --work-dir /work --case "${library_name}"

  printf '%s\n' "${library_root}" >"${project_root}/work/latest-library.txt"
  echo "Library completed: ${library_root}"

elif [[ "${command}" == "query" ]]; then
  library_name=""
  query_id=""
  query_chain=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --library) library_name="${2:?--library requires a value}"; shift 2 ;;
      --query-id) query_id="${2:?--query-id requires a value}"; shift 2 ;;
      --query-chain) query_chain="${2:?--query-chain requires a value}"; shift 2 ;;
      --help|-h) usage; exit 0 ;;
      *) fail "Unknown argument: $1" ;;
    esac
  done
  require_identifier "${library_name}" "library name"
  require_identifier "${query_id}" "query id"
  require_chain "${query_chain}"

  library_root="${project_root}/work/libraries/${library_name}"
  [[ -d "${library_root}" ]] || fail "Library not found: ${library_root}"
  library_catalog="${library_root}/input/library.csv"
  library_runtime="${library_root}/runtime"
  library_data="${library_runtime}/data"
  library_descriptor="${library_runtime}/descriptors/nn_desc.${library_name}.npz"
  [[ -f "${library_catalog}" ]] || fail "Library catalog not found: ${library_catalog}"
  [[ -d "${library_data}" ]] || fail "Library runtime data not found: ${library_data}"
  [[ -f "${library_descriptor}" ]] || fail "Library descriptor not found: ${library_descriptor}"

  query_surface="${query_id}_${query_chain}"
  for required_file in \
    "${query_surface}_surface.npz" \
    "${query_surface}_contacts.${query_surface}.npy" \
    "${query_surface}_within.${query_surface}.npy"; do
    [[ -f "${library_data}/${required_file}" ]] || \
      fail "Query surface is not prepared in the library: ${library_data}/${required_file}"
  done

  # Every catalog surface must have immutable cached search data.  The runtime
  # mounts this directory read-only, which also guarantees SEARCH cannot rewrite it.
  while IFS=, read -r catalog_id catalog_chain catalog_region; do
    [[ "${catalog_id}" == "id" ]] && continue
    catalog_surface="${catalog_id}_${catalog_chain}"
    for required_file in \
      "${catalog_surface}_surface.npz" \
      "${catalog_surface}_contacts.${catalog_surface}.npy" \
      "${catalog_surface}_within.${catalog_surface}.npy"; do
      [[ -f "${library_data}/${required_file}" ]] || \
        fail "Library cache is incomplete: ${library_data}/${required_file}"
    done
  done <"${library_catalog}"

  timestamp="$(date -u +%Y%m%d-%H%M%S-%N)"
  case_name="${query_surface}-${library_name}-${timestamp}"
  run_root="${project_root}/work/searches/${case_name}"
  result_root="${run_root}/results/${case_name}_results"
  mkdir -p \
    "${run_root}/data" "${run_root}/config" "${run_root}/descriptors" \
    "${result_root}" "${run_root}/logs" "${run_root}/manifest"
  ln -s "results/${case_name}_results" "${run_root}/${case_name}_results"

  # Search code uses CASE for both the result prefix and descriptor filename.
  # Hard links give this run its expected descriptor names without copying 2.2 GB.
  ln "${library_descriptor}" "${run_root}/nn_desc.${case_name}.npz"
  ln "${library_descriptor}" "${run_root}/descriptors/nn_desc.${case_name}.npz"

  target="${query_surface}.${query_surface}"
  docker run --rm \
    --cpus "${QUERY_CPUS}" \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    -e OMP_NUM_THREADS="${QUERY_CPUS}" \
    -e MKL_NUM_THREADS="${QUERY_CPUS}" \
    -e OPENBLAS_NUM_THREADS="${QUERY_CPUS}" \
    -e NUMEXPR_NUM_THREADS="${QUERY_CPUS}" \
    -e CASE_NAME="${case_name}" \
    -e TARGET_SURFACE="${target}" \
    -v "${library_catalog}:/input/library.csv:ro" \
    -v "${run_root}:/work" \
    -v "${library_data}:/work/data:ro" \
    --entrypoint bash \
    "${RUNTIME_IMAGE}" -lc '
      set -Eeuo pipefail
      python /opt/runtime/prepare_runtime.py \
        --input-csv /input/library.csv \
        --work-dir /work \
        --case "${CASE_NAME}" \
        --scope full \
        --target "${TARGET_SURFACE}"

      cd /work
      python /opt/surfaceid/main.py \
        --device cpu --params /work/config/search.yml \
        2>&1 | tee /work/logs/search.log

      search_tsv="/work/results/${CASE_NAME}_results/${CASE_NAME}_top_hits.tsv"
      python /opt/runtime/validate_runtime.py search "${search_tsv}" \
        | tee /work/logs/validate_search.log

      python /opt/runtime/rank_hits.py \
        --input-tsv "${search_tsv}" \
        --catalog /work/config/input.csv \
        --descriptor "/work/descriptors/nn_desc.${CASE_NAME}.npz" \
        --output-dir "/work/results/${CASE_NAME}_results" \
        --target "${TARGET_SURFACE}" \
        --prefix "${CASE_NAME}" \
        | tee /work/logs/rank_search.log

      python /opt/runtime/validate_runtime.py ranked \
        "/work/results/${CASE_NAME}_results/${CASE_NAME}_ranked_hits.tsv" \
        "/work/results/${CASE_NAME}_results/${CASE_NAME}_ranked_surfaces.tsv" \
        "/work/results/${CASE_NAME}_results/${CASE_NAME}_ranked_pdbs.tsv" \
        | tee /work/logs/validate_ranked.log
    '

  printf '%s\n' "${run_root}" >"${project_root}/work/latest-search.txt"
  echo "Search completed: ${run_root}"
  echo "PDB ranking: ${result_root}/${case_name}_ranked_pdbs.tsv"
else
  usage
  fail "Unknown command: ${command}"
fi
