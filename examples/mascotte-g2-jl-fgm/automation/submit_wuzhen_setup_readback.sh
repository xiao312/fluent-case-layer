#!/usr/bin/env bash
# Stage and submit one immutable MASCOTTE G2 setup/readback-only probe on Wuzhen.

set -euo pipefail

RUN_LABEL=${1:-g2-jl-fgm-setup-readback-$(date -u +%Y%m%dT%H%M%SZ)}
REPOSITORY=$(git rev-parse --show-toplevel)
GIT_COMMIT=$(git -C "${REPOSITORY}" rev-parse HEAD)
GIT_BRANCH=$(git -C "${REPOSITORY}" symbolic-ref --quiet --short HEAD)
SSH_TARGET=${FCL_WUZHEN_SSH_TARGET:-ac8azwcnf1-wuzhen}
REMOTE_ROOT=${FCL_WUZHEN_REMOTE_ROOT:-/work/home/ac8azwcnf1/xk/260831_fluent_case_layer}
SOURCE_PROJECT_ASSETS=${FCL_WUZHEN_SOURCE_PROJECT_ASSETS:-/work/home/ac8azwcnf1/xk/260829_mascotte_g2/revisions/4d40647ebccb2674cadf19f0bf19a02efd26550b/assets}
SOURCE_GENERATED_ROOT=${FCL_WUZHEN_SOURCE_GENERATED_ROOT:-${SOURCE_PROJECT_ASSETS}/generated}
SOURCE_REFERENCE_ROOT=${FCL_WUZHEN_SOURCE_REFERENCE_ROOT:-${SOURCE_PROJECT_ASSETS}/reference}
PYFLUENT_ENV=${FCL_WUZHEN_PYFLUENT_ENV:-/work/home/ac8azwcnf1/xk/envs/dfode-fluent-cantera32}
FLUENT_INSTALL=${FCL_WUZHEN_FLUENT_INSTALL:-/work/home/ac8azwcnf1/apprepo/fluent/2026r1-none}
FLUENT_ENV_SCRIPT=${FCL_WUZHEN_FLUENT_ENV:-${FLUENT_INSTALL}/scripts/env.sh}
WHEELHOUSE=${FCL_WUZHEN_WHEELHOUSE:?set FCL_WUZHEN_WHEELHOUSE to the locked Python 3.11 wheel directory}
ACCOUNT=ac8azwcnf1
PARTITION=wzacnormal03
REMOTE_REVISION=${REMOTE_ROOT}/revisions/${GIT_COMMIT}
REMOTE_RUN=${REMOTE_ROOT}/runs/${RUN_LABEL}
AUTOMATION_RELATIVE=examples/mascotte-g2-jl-fgm/automation
STAGING_CONTRACT=${REPOSITORY}/${AUTOMATION_RELATIVE}/wuzhen-setup-readback-assets.json
WHEEL_MANIFEST=${REPOSITORY}/${AUTOMATION_RELATIVE}/wuzhen-runtime-wheels.sha256
SLURM_SCRIPT=${AUTOMATION_RELATIVE}/run_wuzhen_setup_readback.slurm

if [[ -n $(git -C "${REPOSITORY}" status --porcelain) ]]; then
  echo "Refusing to submit a dirty worktree; commit the exact input state first." >&2
  exit 2
fi
if [[ ! "${RUN_LABEL}" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Run label may contain only letters, digits, dot, underscore, and hyphen." >&2
  exit 2
fi
for path in "${REMOTE_ROOT}" "${SOURCE_GENERATED_ROOT}" "${SOURCE_REFERENCE_ROOT}" \
  "${PYFLUENT_ENV}" "${FLUENT_INSTALL}" "${FLUENT_ENV_SCRIPT}"; do
  if [[ ! "${path}" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
    echo "Remote paths must be absolute and shell-safe: ${path}" >&2
    exit 2
  fi
done
if [[ ! -d "${WHEELHOUSE}" ]]; then
  echo "Locked wheel directory is absent: ${WHEELHOUSE}" >&2
  exit 2
fi
if [[ ! -s "${STAGING_CONTRACT}" || ! -s "${WHEEL_MANIFEST}" ]]; then
  echo "The checked-in staging contract or wheel manifest is absent." >&2
  exit 2
fi

REMOTE_BRANCH_COMMIT=$(
  git -C "${REPOSITORY}" ls-remote origin "refs/heads/${GIT_BRANCH}" | awk '{print $1}'
)
if [[ "${REMOTE_BRANCH_COMMIT}" != "${GIT_COMMIT}" ]]; then
  echo "Refusing submission until origin/${GIT_BRANCH} is exactly ${GIT_COMMIT}." >&2
  exit 2
fi

python3 - "${STAGING_CONTRACT}" "${WHEELHOUSE}" "${WHEEL_MANIFEST}" <<'PY'
import json
import re
import sys
from pathlib import Path

contract_path, wheelhouse_path, wheel_manifest_path = map(Path, sys.argv[1:])
contract = json.loads(contract_path.read_text(encoding="utf-8"))
entries = contract.get("simulation_assets")
required = {
    "g2-medium-mesh",
    "jl9-kinetics",
    "jl9-thermodynamics",
    "jl9-transport",
    "singla-ohstar-relative",
}
if not isinstance(entries, list) or {entry.get("id") for entry in entries} != required:
    raise SystemExit("staging contract does not contain exactly the five approved assets")
for entry in entries:
    if entry.get("source_root") not in {"generated", "reference"}:
        raise SystemExit(f"invalid source root for {entry.get('id')}")
    for key in ("source_path", "staged_path"):
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", entry.get(key, "")):
            raise SystemExit(f"unsafe {key} for {entry.get('id')}")
    if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
        raise SystemExit(f"invalid SHA-256 for {entry.get('id')}")
    if not isinstance(entry.get("size_bytes"), int) or entry["size_bytes"] <= 0:
        raise SystemExit(f"invalid size for {entry.get('id')}")

wheelhouse = wheelhouse_path.resolve()
wheel_lines = [line for line in wheel_manifest_path.read_text().splitlines() if line.strip()]
if len(wheel_lines) != 5:
    raise SystemExit("runtime wheel manifest must contain exactly five wheels")
for line in wheel_lines:
    digest, filename = line.split(maxsplit=1)
    filename = filename.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or not re.fullmatch(
        r"[A-Za-z0-9_.+-]+\.whl", filename
    ):
        raise SystemExit("invalid runtime wheel manifest entry")
    path = wheelhouse / filename
    if not path.is_file():
        raise SystemExit(f"locked runtime wheel is absent: {path}")
    import hashlib

    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise SystemExit(f"runtime wheel hash mismatch: {path}")
expected_wheels = {line.split(maxsplit=1)[1].strip() for line in wheel_lines}
observed_wheels = {path.name for path in wheelhouse.glob("*.whl")}
if observed_wheels != expected_wheels:
    raise SystemExit("wheelhouse must contain exactly the five locked wheel files")
PY

mapfile -t ASSET_ROWS < <(
  python3 - "${STAGING_CONTRACT}" <<'PY'
import json
import sys

for item in json.load(open(sys.argv[1], encoding="utf-8"))["simulation_assets"]:
    print("\t".join(str(item[key]) for key in (
        "id", "source_root", "source_path", "staged_path", "sha256", "size_bytes"
    )))
PY
)
mapfile -t WHEEL_FILES < <(awk '{print $2}' "${WHEEL_MANIFEST}")

for row in "${ASSET_ROWS[@]}"; do
  IFS=$'\t' read -r identifier source_kind source_path staged_path expected_sha expected_size \
    <<< "${row}"
  if [[ "${source_kind}" == "generated" ]]; then
    source_file=${SOURCE_GENERATED_ROOT}/${source_path}
  else
    source_file=${SOURCE_REFERENCE_ROOT}/${source_path}
  fi
  ssh -o BatchMode=yes "${SSH_TARGET}" \
    "test -f '${source_file}' && test \"\$(stat -c %s '${source_file}')\" = '${expected_size}' && test \"\$(sha256sum '${source_file}' | awk '{print \$1}')\" = '${expected_sha}'" \
    || {
      echo "Remote source asset failed preflight: ${identifier} (${source_file})" >&2
      exit 3
    }
done

REPOSITORY_MANIFEST=$(
  python3 - "${REPOSITORY}" <<'PY'
import hashlib
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
tracked = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
for raw in tracked.split(b"\0"):
    if not raw:
        continue
    relative = raw.decode("utf-8")
    digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    print(f"{digest}  repository/{relative}")
PY
)
ASSET_MANIFEST=$(
  python3 - "${STAGING_CONTRACT}" <<'PY'
import json
import sys

for item in json.load(open(sys.argv[1], encoding="utf-8"))["simulation_assets"]:
    print(f"{item['sha256']}  {item['staged_path']}")
PY
)
WHEEL_SNAPSHOT_MANIFEST=$(
  awk '{digest=$1; $1=""; sub(/^  */, "", $0); print digest "  runtime-wheels/" $0}' \
    "${WHEEL_MANIFEST}"
)
SNAPSHOT_MANIFEST=$(
  printf '%s\n%s\n%s\n' \
    "${REPOSITORY_MANIFEST}" "${ASSET_MANIFEST}" "${WHEEL_SNAPSHOT_MANIFEST}" \
    | sed '/^$/d' | LC_ALL=C sort
)
SNAPSHOT_SHA256=$(printf '%s\n' "${SNAPSHOT_MANIFEST}" | sha256sum | awk '{print $1}')
EXPECTED_MARKER=$(printf 'commit=%s\nsnapshot_sha256=%s' "${GIT_COMMIT}" "${SNAPSHOT_SHA256}")

REMOTE_MARKER=$(
  ssh -o BatchMode=yes "${SSH_TARGET}" \
    "test -f '${REMOTE_REVISION}/.snapshot-complete' && cat '${REMOTE_REVISION}/.snapshot-complete'" \
    || true
)
if [[ -n "${REMOTE_MARKER}" ]]; then
  if [[ "${REMOTE_MARKER}" != "${EXPECTED_MARKER}" ]]; then
    echo "Remote revision marker differs from the exact local snapshot." >&2
    exit 3
  fi
else
  REMOTE_STAGE=${REMOTE_ROOT}/staging/${GIT_COMMIT}.${RUN_LABEL}.$$
  ssh -o BatchMode=yes "${SSH_TARGET}" \
    "umask 0002; mkdir -p '${REMOTE_ROOT}/staging' '${REMOTE_ROOT}/revisions'; test ! -e '${REMOTE_REVISION}'; test ! -e '${REMOTE_STAGE}'; mkdir -p '${REMOTE_STAGE}/repository' '${REMOTE_STAGE}/runtime-assets/mesh' '${REMOTE_STAGE}/runtime-assets/jl9' '${REMOTE_STAGE}/runtime-assets/reference' '${REMOTE_STAGE}/runtime-wheels'"
  git -C "${REPOSITORY}" archive --format=tar "${GIT_COMMIT}" \
    | ssh -o BatchMode=yes "${SSH_TARGET}" "tar -xf - -C '${REMOTE_STAGE}/repository'"

  for row in "${ASSET_ROWS[@]}"; do
    IFS=$'\t' read -r identifier source_kind source_path staged_path expected_sha expected_size \
      <<< "${row}"
    if [[ "${source_kind}" == "generated" ]]; then
      source_file=${SOURCE_GENERATED_ROOT}/${source_path}
    else
      source_file=${SOURCE_REFERENCE_ROOT}/${source_path}
    fi
    ssh -o BatchMode=yes "${SSH_TARGET}" \
      "cp -- '${source_file}' '${REMOTE_STAGE}/${staged_path}'"
  done
  printf '%s\n' "${WHEEL_FILES[@]}" | rsync -az --files-from=- \
    "${WHEELHOUSE}/" "${SSH_TARGET}:${REMOTE_STAGE}/runtime-wheels/"
  printf '%s\n' "${SNAPSHOT_MANIFEST}" | ssh -o BatchMode=yes "${SSH_TARGET}" \
    "cat > '${REMOTE_STAGE}/.snapshot-manifest.sha256'"
  ssh -o BatchMode=yes "${SSH_TARGET}" \
    "cd '${REMOTE_STAGE}' && sha256sum -c .snapshot-manifest.sha256 >/dev/null && test ! -e '${REMOTE_REVISION}' && mv '${REMOTE_STAGE}' '${REMOTE_REVISION}' && printf '%s\n' 'commit=${GIT_COMMIT}' 'snapshot_sha256=${SNAPSHOT_SHA256}' > '${REMOTE_REVISION}/.snapshot-complete'"
fi

SBATCH_RESULT=$(
  ssh -o BatchMode=yes "${SSH_TARGET}" \
    "test ! -e '${REMOTE_RUN}' && mkdir -p '${REMOTE_RUN}' && /opt/gridview/slurm/bin/sbatch --parsable --job-name='fcl-g2-fgm-probe' --account='${ACCOUNT}' --partition='${PARTITION}' --nodes=1 --ntasks=1 --cpus-per-task=4 --mem=7G --time=00:20:00 --output='${REMOTE_RUN}/slurm-%j.out' --error='${REMOTE_RUN}/slurm-%j.err' --export=ALL,REVISION_ROOT='${REMOTE_REVISION}',REPO_ROOT='${REMOTE_REVISION}/repository',RUN_DIR='${REMOTE_RUN}',INPUT_GIT_COMMIT='${GIT_COMMIT}',INPUT_GIT_BRANCH='${GIT_BRANCH}',INPUT_SNAPSHOT_SHA256='${SNAPSHOT_SHA256}',SOURCE_GENERATED_ROOT='${SOURCE_GENERATED_ROOT}',SOURCE_REFERENCE_ROOT='${SOURCE_REFERENCE_ROOT}',PYFLUENT_ENV='${PYFLUENT_ENV}',FLUENT_INSTALL='${FLUENT_INSTALL}',FLUENT_ENV_SCRIPT='${FLUENT_ENV_SCRIPT}',SCNET_SLURM_ACCOUNT='${ACCOUNT}',SCNET_SLURM_PARTITION='${PARTITION}' '${REMOTE_REVISION}/repository/${SLURM_SCRIPT}'"
)
JOB_ID=${SBATCH_RESULT%%;*}
if [[ ! "${JOB_ID}" =~ ^[0-9]+$ ]]; then
  echo "Unexpected sbatch response: ${SBATCH_RESULT}" >&2
  exit 4
fi

printf 'job_id=%s run=%s revision=%s commit=%s snapshot_sha256=%s target=%s\n' \
  "${JOB_ID}" "${REMOTE_RUN}" "${REMOTE_REVISION}" "${GIT_COMMIT}" \
  "${SNAPSHOT_SHA256}" "${SSH_TARGET}"
