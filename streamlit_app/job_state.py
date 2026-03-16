"""
Job state persistence for OpenSPGen Streamlit app.

Each job gets a directory under `jobs/` with a `job_meta.json` file that
tracks every piece of information needed to resume, inspect, or re-run a step.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

_DEFAULT_NSLOTS = max(2, os.cpu_count() or 2)

JOBS_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jobs")
)

STEPS = ["resolve", "conformer", "nwchem", "parse", "sigma"]

STEP_LABELS = {
    "resolve": "1. Identifier Resolution",
    "conformer": "2. Conformer Generation",
    "nwchem": "3. NWChem DFT + COSMO",
    "parse": "4. Parse Results",
    "sigma": "5. Sigma Profile",
}

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_SKIPPED = "skipped"


@dataclass
class JobState:
    """Serialisable state for a single sigma-profile generation job."""

    # --- identity ---
    job_id: str = ""
    job_dir: str = ""

    # --- user inputs ---
    identifier: str = ""
    identifier_type: str = "CAS-Number"
    charge: Optional[int] = 0
    name: str = ""
    nslots: int = _DEFAULT_NSLOTS
    config: str = "COSMO_BP86_TZVP"
    noautoz: bool = False
    iodine: bool = False
    initial_xyz: Optional[str] = None  # absolute host path, or None
    sigma_bins: list = field(default_factory=lambda: [-0.250, 0.250, 0.001])
    avg_radius: Optional[float] = None

    # --- resolved data ---
    smiles: Optional[str] = None
    resolved_charge: Optional[int] = None
    cross_check_warning: Optional[str] = None

    # --- progress ---
    current_step: str = "resolve"
    step_status: dict = field(
        default_factory=lambda: {s: STATUS_PENDING for s in STEPS}
    )
    docker_container_id: Optional[str] = None
    nwchem_phase: str = "not_started"  # not_started | vacuum_opt | cosmo_opt | finished | error
    created_at: str = ""
    updated_at: str = ""
    error: Optional[str] = None

    # --- helpers ---
    def save(self):
        self.updated_at = _now()
        os.makedirs(self.job_dir, exist_ok=True)
        path = os.path.join(self.job_dir, "job_meta.json")
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def load(cls, job_dir: str) -> "JobState":
        path = os.path.join(job_dir, "job_meta.json")
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    def mark_step(self, step: str, status: str, error: Optional[str] = None):
        self.step_status[step] = status
        self.current_step = step
        if error:
            self.error = error
        self.save()

    def next_pending_step(self) -> Optional[str]:
        for s in STEPS:
            if self.step_status[s] == STATUS_PENDING:
                return s
        return None

    def is_complete(self) -> bool:
        return all(
            v in (STATUS_DONE, STATUS_SKIPPED) for v in self.step_status.values()
        )

    def has_error(self) -> bool:
        return any(v == STATUS_ERROR for v in self.step_status.values())

    # --- file paths ---
    @property
    def subfolder(self) -> str:
        """The work subfolder where NWChem files live."""
        return os.path.join(self.job_dir, "nwchem_run")

    @property
    def initial_geometry_path(self) -> str:
        return os.path.join(self.subfolder, "initialGeometry.xyz")

    @property
    def input_nw_path(self) -> str:
        return os.path.join(self.subfolder, "input.nw")

    @property
    def output_nw_path(self) -> str:
        return os.path.join(self.subfolder, "output.nw")

    @property
    def nwchem_name(self) -> str:
        """Name used in the NWChem 'start' directive (= subfolder basename)."""
        return os.path.basename(self.subfolder)

    @property
    def cosmo_xyz_path(self) -> str:
        return os.path.join(self.subfolder, f"{self.nwchem_name}.cosmo.xyz")

    @property
    def final_geometry_path(self) -> str:
        return os.path.join(self.subfolder, "finalGeometry.xyz")

    @property
    def sigma_surface_path(self) -> str:
        return os.path.join(self.subfolder, "sigmaSurface.csv")

    @property
    def sigma_profile_path(self) -> str:
        return os.path.join(self.subfolder, "sigmaProfile.csv")

    @property
    def output_summary_path(self) -> str:
        return os.path.join(self.subfolder, "outputSummary.nw")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def create_job(
    identifier: str,
    identifier_type: str,
    name: str,
    charge: int = 0,
    nslots: int = _DEFAULT_NSLOTS,
    config: str = "COSMO_BP86_TZVP",
    noautoz: bool = False,
    iodine: bool = False,
    initial_xyz: Optional[str] = None,
    avg_radius: Optional[float] = None,
) -> JobState:
    """Create a new job with a unique ID and directory."""
    import re as _re
    safe_name = _re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
    job_id = f"{safe_name}_{int(time.time())}"
    job_dir = os.path.join(JOBS_ROOT, job_id)
    os.makedirs(job_dir, exist_ok=True)

    state = JobState(
        job_id=job_id,
        job_dir=job_dir,
        identifier=identifier,
        identifier_type=identifier_type,
        charge=charge,
        name=name,
        nslots=nslots,
        config=config,
        noautoz=noautoz,
        iodine=iodine,
        initial_xyz=initial_xyz,
        avg_radius=avg_radius,
        created_at=_now(),
    )
    state.save()
    return state


def list_jobs() -> list[JobState]:
    """Return all jobs sorted newest-first."""
    if not os.path.isdir(JOBS_ROOT):
        return []
    jobs = []
    for d in sorted(os.listdir(JOBS_ROOT), reverse=True):
        meta = os.path.join(JOBS_ROOT, d, "job_meta.json")
        if os.path.isfile(meta):
            try:
                jobs.append(JobState.load(os.path.join(JOBS_ROOT, d)))
            except Exception:
                pass
    return jobs
