#!/usr/bin/env bash
#SBATCH --job-name=fcl-g2-fgm-probe
#SBATCH --account=ac8azwcnf1
#SBATCH --partition=wzacnormal03
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=7G
#SBATCH --time=00:20:00

set -euo pipefail

: "${REVISION_ROOT:?REVISION_ROOT is required}"
: "${REPO_ROOT:?REPO_ROOT is required}"
: "${RUN_DIR:?RUN_DIR is required}"
: "${INPUT_GIT_COMMIT:?INPUT_GIT_COMMIT is required}"
: "${INPUT_GIT_BRANCH:?INPUT_GIT_BRANCH is required}"
: "${INPUT_SNAPSHOT_SHA256:?INPUT_SNAPSHOT_SHA256 is required}"
: "${SOURCE_GENERATED_ROOT:?SOURCE_GENERATED_ROOT is required}"
: "${SOURCE_REFERENCE_ROOT:?SOURCE_REFERENCE_ROOT is required}"
: "${PYFLUENT_ENV:?PYFLUENT_ENV is required}"
: "${FLUENT_INSTALL:?FLUENT_INSTALL is required}"
: "${FLUENT_ENV_SCRIPT:?FLUENT_ENV_SCRIPT is required}"
: "${SCNET_SLURM_ACCOUNT:?SCNET_SLURM_ACCOUNT is required}"
: "${SCNET_SLURM_PARTITION:?SCNET_SLURM_PARTITION is required}"

AUTOMATION=${REPO_ROOT}/examples/mascotte-g2-jl-fgm/automation
CASE_ROOT=${REPO_ROOT}/examples/mascotte-g2-jl-fgm/case
STAGING_CONTRACT=${AUTOMATION}/wuzhen-setup-readback-assets.json
WHEEL_MANIFEST=${AUTOMATION}/wuzhen-runtime-wheels.sha256
SCNET_WORK_ROOT=/work/home/ac8azwcnf1/xk
RANKS=1

mkdir -p "${RUN_DIR}" "${RUN_DIR}/python-deps" \
  "${SCNET_WORK_ROOT}/cache/matplotlib" "${SCNET_WORK_ROOT}/tmp/${SLURM_JOB_ID}"
cd "${RUN_DIR}"
exec > >(tee "${RUN_DIR}/campaign.log") 2>&1

test "${SCNET_SLURM_ACCOUNT}" = ac8azwcnf1
test "${SCNET_SLURM_PARTITION}" = wzacnormal03
test "${SLURM_NTASKS}" = 1
test "${SLURM_CPUS_PER_TASK}" = 4
test -s "${REVISION_ROOT}/.snapshot-complete"
grep -Fx "commit=${INPUT_GIT_COMMIT}" "${REVISION_ROOT}/.snapshot-complete"
grep -Fx "snapshot_sha256=${INPUT_SNAPSHOT_SHA256}" "${REVISION_ROOT}/.snapshot-complete"
(cd "${REVISION_ROOT}" && sha256sum -c .snapshot-manifest.sha256)
test -x "${PYFLUENT_ENV}/bin/python"
test -s "${FLUENT_ENV_SCRIPT}"

export LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-}
source "${FLUENT_ENV_SCRIPT}"
export AWP_ROOT261="${FLUENT_INSTALL}/app/v261"
export FLUENT_ARCH=lnamd64
export PATH="${PYFLUENT_ENV}/bin:${AWP_ROOT261}/fluent/bin:${PATH}"
export PROGLIST="${AWP_ROOT261}/fluent/bin/fluent"
export CONTAINER_IMAGE=scnet-compute-runtime:wuzhen-default
test -x "${PROGLIST}"

"${PYFLUENT_ENV}/bin/python" -m pip install --disable-pip-version-check \
  --no-index --no-deps --target "${RUN_DIR}/python-deps" \
  "${REVISION_ROOT}"/runtime-wheels/*.whl

export PYTHONPATH="${RUN_DIR}/python-deps:${REPO_ROOT}/src"
export MASCOTTE_G2_ASSET_ROOT="${REVISION_ROOT}/runtime-assets"
export MASCOTTE_G2_REFERENCE_ROOT="${REVISION_ROOT}/runtime-assets/reference"
export FLUENT_AFFINITY=0
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONUTF8=1 LANG=C LC_ALL=C
export XDG_CACHE_HOME="${SCNET_WORK_ROOT}/cache/xdg"
export MPLCONFIGDIR="${SCNET_WORK_ROOT}/cache/matplotlib"
export TMPDIR="${SCNET_WORK_ROOT}/tmp/${SLURM_JOB_ID}"

HOST_FILE=${RUN_DIR}/fluent.hosts
srun --ntasks="${RANKS}" hostname | sort | uniq -c | awk '{print $2 ":" $1}' > "${HOST_FILE}"
export FLUENT_ADDITIONAL_ARGUMENTS="-pinfiniband -t${RANKS} -cnf=${HOST_FILE} -mpi=intel -ssh -pmpi-auto-selected"

PROVENANCE=${RUN_DIR}/execution-provenance.json
EVIDENCE=${RUN_DIR}/setup-readback.json
VERIFICATION=${RUN_DIR}/verification.json

"${PYFLUENT_ENV}/bin/python" "${AUTOMATION}/write_wuzhen_provenance.py" \
  --revision-root "${REVISION_ROOT}" \
  --repository-root "${REPO_ROOT}" \
  --run-dir "${RUN_DIR}" \
  --staging-contract "${STAGING_CONTRACT}" \
  --wheel-manifest "${WHEEL_MANIFEST}" \
  --output "${PROVENANCE}" \
  --git-commit "${INPUT_GIT_COMMIT}" \
  --git-branch "${INPUT_GIT_BRANCH}" \
  --snapshot-sha256 "${INPUT_SNAPSHOT_SHA256}" \
  --source-generated-root "${SOURCE_GENERATED_ROOT}" \
  --source-reference-root "${SOURCE_REFERENCE_ROOT}" \
  --fluent-install "${FLUENT_INSTALL}" \
  --pyfluent-environment "${PYFLUENT_ENV}" \
  --hostfile "${HOST_FILE}" \
  --account "${SCNET_SLURM_ACCOUNT}" \
  --partition "${SCNET_SLURM_PARTITION}" \
  --ranks "${RANKS}"

"${PYFLUENT_ENV}/bin/python" -u "${AUTOMATION}/setup_readback_smoke.py" \
  --case "${CASE_ROOT}" \
  --output "${EVIDENCE}" \
  --execution-provenance "${PROVENANCE}" \
  --processors "${RANKS}" \
  --confirm-setup-readback-only

"${PYFLUENT_ENV}/bin/python" "${AUTOMATION}/verify_wuzhen_setup_readback.py" \
  --case "${CASE_ROOT}" \
  --evidence "${EVIDENCE}" \
  --execution-provenance "${PROVENANCE}" \
  --staging-contract "${STAGING_CONTRACT}" \
  --verification "${VERIFICATION}" \
  --expected-commit "${INPUT_GIT_COMMIT}" \
  --expected-snapshot-sha256 "${INPUT_SNAPSHOT_SHA256}" \
  --expected-job-id "${SLURM_JOB_ID}"

sha256sum "${PROVENANCE}" "${EVIDENCE}" "${VERIFICATION}" \
  > "${RUN_DIR}/evidence.sha256"
touch "${RUN_DIR}/SUCCESS"
echo "status=verified_setup_readback_complete job_id=${SLURM_JOB_ID}"
