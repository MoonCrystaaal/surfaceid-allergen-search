#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_DIR=/opt/surfaceid
readonly TOOL_DIR=/opt/runtime
readonly DEFAULT_INPUT_CSV=/opt/surfaceid/test/input.csv

OUTPUT_UID="${OUTPUT_UID:-1026}"
OUTPUT_GID="${OUTPUT_GID:-1026}"
restore_search=""
restore_target=""

usage() {
  cat <<'EOF'
Usage:
  surfaceid-runtime --check

  # Existing contact-interface workflow
  surfaceid-runtime --mode desc|search|align|all --scope contact \
    --input-npz-dir /input/npz --input-csv /input/input.csv --work-dir /work

  # Build a reusable whole-surface library descriptor
  surfaceid-runtime --mode desc --scope full \
    --input-npz-dir /input/npz --input-csv /input/library.csv \
    --work-dir /library --case library-name

  # Search one whole or XYZ-restricted query against that library
  surfaceid-runtime --mode query --scope full|restricted \
    --input-npz-dir /library/npz --input-csv /library/library.csv \
    --library-descriptor /library/nn_desc.library-name.npz \
    --query-npz /query/QUERY_A_surface.npz --target-surface QUERY_A \
    [--query-xyz /query/QUERY_A.xyz] [--align-top 20] [--no-align] \
    --work-dir /work --case query-case

Contact catalog columns: id,Ag,Ab
Full-surface library catalog columns: id,chain,region (region must be F)
EOF
}

safe_chown_outputs() {
  local work_dir="$1"
  local case_name="$2"
  local path
  for path in data config descriptors results logs manifest; do
    if [[ -d "${work_dir}/${path}" ]]; then
      chown -R "${OUTPUT_UID}:${OUTPUT_GID}" "${work_dir}/${path}" || true
    fi
  done
  for path in "${work_dir}/${case_name}_results" "${work_dir}/nn_desc.${case_name}.npz"; do
    if [[ -L "${path}" ]]; then
      chown -h "${OUTPUT_UID}:${OUTPUT_GID}" "${path}" || true
    fi
  done
}

cleanup() {
  if [[ -n "${restore_search}" && -f "${restore_search}" && -n "${restore_target}" ]]; then
    mv -f "${restore_search}" "${restore_target}" || true
  fi
  safe_chown_outputs "${work_dir:-/work}" "${case_name:-validation}"
}

run_stage() {
  local stage="$1"
  local config="$2"
  local work="$3"
  local log_file="${work}/logs/${stage}.log"
  (
    cd "${work}"
    python "${APP_DIR}/main.py" --device cpu --params "${config}"
  ) 2>&1 | tee "${log_file}"
}

ensure_result_paths() {
  local work="$1"
  local case="$2"
  result_target="${work}/results/${case}_results"
  result_link="${work}/${case}_results"
  mkdir -p "${result_target}"
  if [[ ! -e "${result_link}" ]]; then
    ln -s "results/${case}_results" "${result_link}"
  fi
}

ensure_descriptor_link() {
  local work="$1"
  local case="$2"
  local final="${work}/descriptors/nn_desc.${case}.npz"
  local root="${work}/nn_desc.${case}.npz"
  [[ -f "${final}" ]] || { echo "Descriptor missing: ${final}" >&2; exit 2; }
  if [[ ! -e "${root}" ]]; then
    ln -s "descriptors/nn_desc.${case}.npz" "${root}"
  fi
}

write_versions() {
  local work="$1"
  python - <<'PY' >"${work}/manifest/runtime-versions.txt"
import Bio, numpy, pandas, scipy, sklearn, torch, torch_scatter
print("python_torch=" + torch.__version__)
print("torch_cuda=" + str(torch.version.cuda))
print("torch_scatter=" + getattr(torch_scatter, "__version__", "unknown"))
print("numpy=" + numpy.__version__)
print("pandas=" + pandas.__version__)
print("scipy=" + scipy.__version__)
print("sklearn=" + sklearn.__version__)
print("biopython=" + Bio.__version__)
PY
}

if [[ $# -eq 0 || "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--check" ]]; then
  exec python "${TOOL_DIR}/runtime_check.py"
fi

mode=""
scope="contact"
input_npz_dir=""
input_csv="${DEFAULT_INPUT_CSV}"
work_dir="/work"
case_name="validation"
target=""
target_surface=""
query_npz=""
query_xyz=""
library_descriptor=""
align_top=20
run_alignment=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) mode="${2:?--mode requires a value}"; shift 2 ;;
    --scope) scope="${2:?--scope requires a value}"; shift 2 ;;
    --input-npz-dir) input_npz_dir="${2:?--input-npz-dir requires a path}"; shift 2 ;;
    --input-csv) input_csv="${2:?--input-csv requires a path}"; shift 2 ;;
    --work-dir) work_dir="${2:?--work-dir requires a path}"; shift 2 ;;
    --case) case_name="${2:?--case requires a value}"; shift 2 ;;
    --target) target="${2:?--target requires a value}"; shift 2 ;;
    --target-surface) target_surface="${2:?--target-surface requires a value}"; shift 2 ;;
    --query-npz) query_npz="${2:?--query-npz requires a path}"; shift 2 ;;
    --query-xyz) query_xyz="${2:?--query-xyz requires a path}"; shift 2 ;;
    --library-descriptor) library_descriptor="${2:?--library-descriptor requires a path}"; shift 2 ;;
    --align-top) align_top="${2:?--align-top requires a value}"; shift 2 ;;
    --no-align) run_alignment=0; shift ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "${mode}" in desc|search|align|all|query) ;; *) echo '--mode must be desc, search, align, all, or query' >&2; exit 2 ;; esac
case "${scope}" in contact|full|restricted) ;; *) echo '--scope must be contact, full, or restricted' >&2; exit 2 ;; esac
[[ -d "${work_dir}" ]] || { echo "Work directory must be a bind mount: ${work_dir}" >&2; exit 2; }
[[ -f "${input_csv}" ]] || { echo "Input CSV not found: ${input_csv}" >&2; exit 2; }
[[ "${align_top}" =~ ^[0-9]+$ ]] || { echo '--align-top must be a non-negative integer' >&2; exit 2; }

mkdir -p "${work_dir}"/{data,config,descriptors,results,logs,manifest}
trap cleanup EXIT

if [[ "${mode}" == "query" ]]; then
  [[ "${scope}" == "full" || "${scope}" == "restricted" ]] || {
    echo 'Query mode requires --scope full or restricted' >&2; exit 2;
  }
  [[ -d "${input_npz_dir}" ]] || { echo "Library NPZ directory not found: ${input_npz_dir}" >&2; exit 2; }
  [[ -f "${query_npz}" ]] || { echo "Query NPZ not found: ${query_npz}" >&2; exit 2; }
  [[ -f "${library_descriptor}" ]] || { echo "Library descriptor not found: ${library_descriptor}" >&2; exit 2; }
  [[ "${target_surface}" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo 'Invalid --target-surface' >&2; exit 2; }
  if [[ "${scope}" == "restricted" ]]; then
    [[ -f "${query_xyz}" ]] || { echo "Restricted query XYZ not found: ${query_xyz}" >&2; exit 2; }
  fi
  target="${target_surface}.${target_surface}"

  python "${TOOL_DIR}/prepare_runtime.py" \
    --input-csv "${input_csv}" \
    --input-npz-dir "${input_npz_dir}" \
    --query-npz "${query_npz}" \
    --library-descriptor "${library_descriptor}" \
    --work-dir "${work_dir}" \
    --case "${case_name}" \
    --scope "${scope}" \
    --target "${target}" \
    --initialize

  query_npz_installed="${work_dir}/data/$(basename "${query_npz}")"
  region_args=(
    --surface-npz "${query_npz_installed}"
    --surface-id "${target_surface}"
    --output-dir "${work_dir}/data"
    --scope "${scope}"
  )
  if [[ "${scope}" == "restricted" ]]; then
    region_args+=(--xyz "${query_xyz}")
    cp "${query_xyz}" "${work_dir}/manifest/${target_surface}.xyz"
  fi
  python "${TOOL_DIR}/prepare_query_region.py" "${region_args[@]}" \
    | tee "${work_dir}/logs/query_region.log"

  ensure_result_paths "${work_dir}" "${case_name}"
  ensure_descriptor_link "${work_dir}" "${case_name}"
  python "${TOOL_DIR}/validate_runtime.py" descriptor \
    "${work_dir}/descriptors/nn_desc.${case_name}.npz" \
    | tee "${work_dir}/logs/validate_descriptor.log"
  run_stage search "${work_dir}/config/search.yml" "${work_dir}"
  search_tsv="${result_target}/${case_name}_top_hits.tsv"
  python "${TOOL_DIR}/validate_runtime.py" search "${search_tsv}" \
    | tee "${work_dir}/logs/validate_search.log"

  alignment_input="${result_target}/${case_name}_alignment_input.tsv"
  rank_args=(
    --input-tsv "${search_tsv}"
    --catalog "${work_dir}/config/input.csv"
    --descriptor "${work_dir}/descriptors/nn_desc.${case_name}.npz"
    --output-dir "${result_target}"
    --target "${target}"
    --prefix "${case_name}"
  )
  if [[ "${run_alignment}" -eq 1 ]]; then
    rank_args+=(--align-top "${align_top}" --alignment-input "${alignment_input}")
  fi
  python "${TOOL_DIR}/rank_hits.py" "${rank_args[@]}" \
    | tee "${work_dir}/logs/rank_search.log"

  if [[ "${run_alignment}" -eq 1 && "$(wc -l < "${alignment_input}")" -gt 1 ]]; then
    full_search_tsv="${result_target}/${case_name}_top_hits.full.tsv"
    mv "${search_tsv}" "${full_search_tsv}"
    restore_search="${full_search_tsv}"
    restore_target="${search_tsv}"
    cp "${alignment_input}" "${search_tsv}"
    run_stage align "${work_dir}/config/align.yml" "${work_dir}"
    aligned_tsv="${result_target}/${case_name}_top_hits_aligned.tsv"
    python "${TOOL_DIR}/validate_runtime.py" align "${aligned_tsv}" \
      | tee "${work_dir}/logs/validate_align.log"
    rm -f "${search_tsv}"
    mv "${full_search_tsv}" "${search_tsv}"
    restore_search=""
    restore_target=""
    python "${TOOL_DIR}/rank_hits.py" \
      --input-tsv "${search_tsv}" \
      --aligned-tsv "${aligned_tsv}" \
      --catalog "${work_dir}/config/input.csv" \
      --descriptor "${work_dir}/descriptors/nn_desc.${case_name}.npz" \
      --output-dir "${result_target}" \
      --target "${target}" \
      --prefix "${case_name}" \
      | tee "${work_dir}/logs/rank_aligned.log"
  fi

  python "${TOOL_DIR}/validate_runtime.py" ranked \
    "${result_target}/${case_name}_ranked_hits.tsv" \
    "${result_target}/${case_name}_ranked_surfaces.tsv" \
    "${result_target}/${case_name}_ranked_pdbs.tsv" \
    | tee "${work_dir}/logs/validate_ranked.log"
else
  prepare_args=(
    --input-csv "${input_csv}"
    --work-dir "${work_dir}"
    --case "${case_name}"
    --scope "${scope}"
  )
  if [[ -n "${target}" ]]; then
    prepare_args+=(--target "${target}")
  fi
  if [[ "${mode}" == desc || "${mode}" == all ]]; then
    [[ -d "${input_npz_dir}" ]] || { echo "Input NPZ directory not found: ${input_npz_dir}" >&2; exit 2; }
    prepare_args+=(--input-npz-dir "${input_npz_dir}" --initialize)
  fi
  python "${TOOL_DIR}/prepare_runtime.py" "${prepare_args[@]}"
  ensure_result_paths "${work_dir}" "${case_name}"

  if [[ "${mode}" == desc || "${mode}" == all ]]; then
    run_stage desc "${work_dir}/config/desc.yml" "${work_dir}"
    descriptor_root="${work_dir}/nn_desc.${case_name}.npz"
    descriptor_final="${work_dir}/descriptors/nn_desc.${case_name}.npz"
    [[ -f "${descriptor_root}" ]] || { echo "Descriptor not produced: ${descriptor_root}" >&2; exit 1; }
    mv "${descriptor_root}" "${descriptor_final}"
    ln -s "descriptors/nn_desc.${case_name}.npz" "${descriptor_root}"
    python "${TOOL_DIR}/validate_runtime.py" descriptor "${descriptor_final}" \
      | tee "${work_dir}/logs/validate_descriptor.log"
  fi

  if [[ "${mode}" == search || "${mode}" == all ]]; then
    ensure_descriptor_link "${work_dir}" "${case_name}"
    run_stage search "${work_dir}/config/search.yml" "${work_dir}"
    search_tsv="${result_target}/${case_name}_top_hits.tsv"
    python "${TOOL_DIR}/validate_runtime.py" search "${search_tsv}" \
      | tee "${work_dir}/logs/validate_search.log"
  fi

  if [[ "${mode}" == align || "${mode}" == all ]]; then
    search_tsv="${result_target}/${case_name}_top_hits.tsv"
    [[ -f "${search_tsv}" ]] || { echo "Search result missing: ${search_tsv}" >&2; exit 2; }
    ensure_descriptor_link "${work_dir}" "${case_name}"
    run_stage align "${work_dir}/config/align.yml" "${work_dir}"
    aligned_tsv="${result_target}/${case_name}_top_hits_aligned.tsv"
    python "${TOOL_DIR}/validate_runtime.py" align "${aligned_tsv}" \
      | tee "${work_dir}/logs/validate_align.log"
  fi
fi

if [[ -f "${work_dir}/manifest/input-checksums.sha256" ]]; then
  python "${TOOL_DIR}/validate_runtime.py" inputs \
    "${work_dir}/manifest/input-checksums.sha256" "${work_dir}/data" \
    | tee "${work_dir}/logs/validate_inputs.log"
fi
if [[ -f "${work_dir}/manifest/library-descriptor.sha256" ]]; then
  python "${TOOL_DIR}/validate_runtime.py" inputs \
    "${work_dir}/manifest/library-descriptor.sha256" "${work_dir}/descriptors" \
    | tee "${work_dir}/logs/validate_library_descriptor.log"
fi
write_versions "${work_dir}"

echo "SurfaceID runtime stage(s) completed: ${mode}"
