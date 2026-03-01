"""
Docker-based NWChem execution backend.

The Streamlit app dispatches NWChem DFT+COSMO jobs to sibling Docker
containers via the Docker socket.  Both the Streamlit container and the
NWChem container mount a shared volume at ``/app/jobs``, so files written
by one are visible to the other.

In the future this module can be extended to dispatch to HPC schedulers
(Slurm, PBS, Kubernetes Jobs, etc.) by implementing the same interface:
``launch_nwchem``, ``get_status``, ``get_exit_code``, ``get_logs``,
``stop_and_remove``.
"""

import os
import time
from typing import Optional

import docker
from docker.errors import NotFound, APIError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NWCHEM_IMAGE = os.environ.get("OPENSPGEN_NWCHEM_IMAGE", "openspgen-arm")

# Where the shared jobs volume is mounted inside BOTH containers.
# The Streamlit Dockerfile and the docker-run command must agree on this.
JOBS_MOUNT = "/app/jobs"

# Docker socket — auto-detect OrbStack on macOS, fall back to default.
_ORBSTACK = "/Users/davidebortolami/.orbstack/run/docker.sock"
DOCKER_SOCKET = os.environ.get(
    "DOCKER_HOST",
    f"unix://{_ORBSTACK}" if os.path.exists(_ORBSTACK) else "unix:///var/run/docker.sock",
)


def _client() -> docker.DockerClient:
    return docker.DockerClient(base_url=DOCKER_SOCKET)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def launch_nwchem(
    *,
    job_subfolder: str,
    nslots: int = 8,
    image: str | None = None,
    container_name: str | None = None,
    jobs_volume: str | None = None,
) -> str:
    """
    Launch NWChem in a detached sibling container.

    ``job_subfolder`` is the **absolute path inside the Streamlit container**
    to the directory that already contains ``input.nw`` and
    ``initialGeometry.xyz``.  Because both containers mount the *same*
    Docker volume at ``JOBS_MOUNT``, the path is identical in the NWChem
    container and no translation is needed.

    Returns the Docker container ID.
    """
    image = image or NWCHEM_IMAGE
    client = _client()

    # Normalise job_subfolder so it doesn't contain ".." segments
    # (the NWChem sibling container may not have the same directory tree).
    job_subfolder = os.path.normpath(job_subfolder)

    # Resolve which Docker volume or bind-mount backs /app/jobs.
    vol_name = jobs_volume or _detect_jobs_volume(client)

    cmd = (
        f"bash -c 'cd {job_subfolder} && "
        f"mpirun -np {nslots} nwchem {job_subfolder}/input.nw "
        f"> {job_subfolder}/output.nw 2>&1'"
    )

    # Mount the same jobs volume at the same path
    volumes = {vol_name: {"bind": JOBS_MOUNT, "mode": "rw"}}

    env = {
        "OMPI_ALLOW_RUN_AS_ROOT": "1",
        "OMPI_ALLOW_RUN_AS_ROOT_CONFIRM": "1",
        "OMP_NUM_THREADS": str(nslots),
        "NSLOTS": str(nslots),
    }

    # Remove any stale container with the same name
    cname = container_name or f"spgen_{int(time.time())}"
    try:
        old = client.containers.get(cname)
        old.remove(force=True)
    except (NotFound, APIError):
        pass

    container = client.containers.run(
        image,
        command=cmd,
        name=cname,
        detach=True,
        working_dir=job_subfolder,
        volumes=volumes,
        environment=env,
        auto_remove=False,
    )
    return container.id


def _detect_jobs_volume(client: docker.DockerClient) -> str:
    """
    Figure out the volume/bind source backing ``/app/jobs`` in *this*
    container so we can pass the same source to the NWChem container.

    Falls back to the ``OPENSPGEN_JOBS_VOLUME`` env-var, then to
    ``openspgen-jobs`` (the recommended named volume).
    """
    explicit = os.environ.get("OPENSPGEN_JOBS_VOLUME")
    if explicit:
        return explicit

    # Try introspecting our own container's mounts
    hostname = os.environ.get("HOSTNAME", "")
    if hostname:
        try:
            me = client.containers.get(hostname)
            for mount in me.attrs.get("Mounts", []):
                if mount.get("Destination") == JOBS_MOUNT:
                    return mount.get("Name") or mount.get("Source", "openspgen-jobs")
        except Exception:
            pass

    return "openspgen-jobs"


# ---------------------------------------------------------------------------
# Status / monitoring
# ---------------------------------------------------------------------------

def get_status(container_id: str) -> str:
    """Return 'running', 'exited', 'not_found', etc."""
    try:
        c = _client().containers.get(container_id)
        return c.status
    except NotFound:
        return "not_found"
    except APIError as exc:
        return f"error: {exc}"


def get_exit_code(container_id: str) -> Optional[int]:
    """Return the exit code of a finished container, or None if running."""
    try:
        c = _client().containers.get(container_id)
        if c.status == "exited":
            return c.attrs["State"]["ExitCode"]
        return None
    except (NotFound, APIError):
        return None


def get_logs(container_id: str, tail: int = 200) -> str:
    """Return the last *tail* lines of the container log."""
    try:
        c = _client().containers.get(container_id)
        return c.logs(tail=tail).decode("utf-8", errors="replace")
    except NotFound:
        return "(container not found)"
    except APIError as exc:
        return f"(error: {exc})"


def stop_and_remove(container_id: str) -> None:
    """Stop and remove a container. Silently ignores if gone."""
    try:
        c = _client().containers.get(container_id)
        c.stop(timeout=10)
    except (NotFound, APIError):
        pass
    try:
        c.remove()  # type: ignore[possibly-undefined]
    except Exception:
        pass


# ---------------------------------------------------------------------------
# NWChem-specific log parsing
# ---------------------------------------------------------------------------

def parse_nwchem_progress(output_nw_path: str) -> dict:
    """
    Parse an ``output.nw`` file on the host to extract NWChem progress info.

    Parameters
    ----------
    output_nw_path : str
        Absolute path to ``output.nw`` on the host filesystem.

    Returns a dict with keys:
        phase        : 'vacuum_opt' | 'cosmo_opt' | 'unknown' | 'finished'
        step         : int or None  (geometry optimisation step number)
        scf_iter     : int or None  (current SCF iteration within step)
        energy       : float or None (last total DFT energy)
        converged    : bool
        walltime_s   : float or None
    """
    info = {
        "phase": "unknown",
        "step": None,
        "scf_iter": None,
        "energy": None,
        "converged": False,
        "walltime_s": None,
    }

    if not os.path.isfile(output_nw_path):
        return info

    # Read last ~2000 lines for efficiency
    try:
        with open(output_nw_path) as f:
            all_lines = f.readlines()
        lines = all_lines[-2000:] if len(all_lines) > 2000 else all_lines
    except Exception:
        return info

    for line in reversed(lines):
        parts = line.split()
        # Detect phase
        if "-cosmo- solvent" in line and info["phase"] == "unknown":
            info["phase"] = "cosmo_opt"
        elif "Optimization converged" in line:
            info["converged"] = True

        # Step number (e.g. "Step   14")
        if "Step" in parts and info["step"] is None:
            try:
                idx = parts.index("Step")
                info["step"] = int(parts[idx + 1])
            except (IndexError, ValueError):
                pass

        # Total DFT energy
        if "Total DFT energy" in line and info["energy"] is None:
            try:
                info["energy"] = float(parts[-1])
            except (IndexError, ValueError):
                pass

        # Wall time
        if "wall:" in line and info["walltime_s"] is None:
            try:
                idx = parts.index("wall:")
                info["walltime_s"] = float(parts[idx + 1].rstrip("s"))
            except (IndexError, ValueError):
                pass

    # Determine phase from order
    if info["phase"] == "unknown":
        for line in lines:
            if "dft gradient" in line.lower() or "nwchem" in line.lower():
                info["phase"] = "vacuum_opt"
                break

    if info["converged"]:
        # Check if both phases finished
        cosmo_found = any("-cosmo- solvent" in ln for ln in lines)
        if cosmo_found:
            last_cosmo = max(
                (i for i, ln in enumerate(lines) if "-cosmo- solvent" in ln),
                default=-1,
            )
            last_opt = max(
                (i for i, ln in enumerate(lines) if "Optimization converged" in ln),
                default=-1,
            )
            if last_opt > last_cosmo:
                info["phase"] = "finished"

    return info
