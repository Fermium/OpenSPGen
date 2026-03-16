"""
Step-based pipeline for sigma-profile generation.

Decomposes the monolithic ``spGenerator.generateSP()`` into five discrete
steps that can be executed (and resumed) independently via the Streamlit UI.

Steps
-----
1. **resolve**    – Convert a CAS / InChI(Key) identifier to a SMILES string
                    via CIRpy + PubChemPy cross-check.
2. **conformer**  – Generate an initial 3-D conformer with RDKit MMFF, *or*
                    copy the user-supplied XYZ file.
3. **nwchem**     – Build the NWChem input file and launch a Docker container
                    running DFT + COSMO geometry optimisation.
4. **parse**      – Read ``output.nw`` and ``*.cosmo.xyz`` once NWChem exits.
                    Generate ``finalGeometry.xyz`` and ``outputSummary.nw``.
5. **sigma**      – Build the sigma surface matrix, apply the averaging
                    algorithm, and compute the histogram sigma profile.

Each step reads / writes to the job directory and updates ``job_meta.json``
through the :pymod:`job_state` module.
"""

import os
import sys
import shutil
import time

import numpy

# ---------------------------------------------------------------------------
# Make the upstream library importable
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PYTHON_DIR = os.path.join(_REPO_ROOT, "Python")
if _PYTHON_DIR not in sys.path:
    sys.path.insert(0, _PYTHON_DIR)

from lib import spGenerator as sp    # crossCheck, getSigmaMatrix, getSigmaProfile
from lib import NWChem_Wrapper as nwc
from lib import RDKit_Wrapper as rdk
from rdkit.Chem import rdmolops

from job_state import (
    JobState,
    STATUS_RUNNING,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_SKIPPED,
)
import docker_runner

# ---------------------------------------------------------------------------
# Step 1 – Identifier resolution
# ---------------------------------------------------------------------------

def step_resolve(state: JobState) -> None:
    """Resolve identifier → SMILES string, update state.

    Also performs optional tautomer enumeration and zwitterion detection
    when the resolved SMILES is available.
    """
    state.mark_step("resolve", STATUS_RUNNING)

    try:
        id_type = state.identifier_type.upper()

        # If the user already supplied SMILES or is providing an XYZ/MOL2
        # with explicit charge, skip the network lookup.
        if id_type == "SMILES":
            state.smiles = state.identifier
            state.resolved_charge = state.charge
        elif state.initial_xyz is not None and state.charge is not None:
            # No need to resolve — we have geometry + charge.
            state.smiles = None
            state.resolved_charge = state.charge
            state.mark_step("resolve", STATUS_SKIPPED)
            return
        else:
            smiles, warning = sp.crossCheck(state.identifier, state.identifier_type)
            state.smiles = smiles
            state.cross_check_warning = warning

        # --- Tautomer enumeration (optional) ---
        if state.smiles and state.enumerate_tautomers:
            state.tautomers = rdk.enumerateTautomers(state.smiles)
            # If the user hasn't already picked a tautomer, default to the
            # input SMILES so the pipeline can proceed automatically.
            if not state.selected_tautomer:
                state.selected_tautomer = state.smiles

        # --- Zwitterion detection ---
        if state.smiles:
            state.is_zwitterion = rdk.detectZwitterion(state.smiles)

        state.mark_step("resolve", STATUS_DONE)

    except Exception as exc:
        state.mark_step("resolve", STATUS_ERROR, error=str(exc))
        raise


# ---------------------------------------------------------------------------
# Step 2 – Conformer generation
# ---------------------------------------------------------------------------

def step_conformer(state: JobState) -> None:
    """Generate (or copy) the initial XYZ geometry."""
    state.mark_step("conformer", STATUS_RUNNING)

    try:
        # Ensure sub-folder exists (e.g.  jobs/<id>/<id>_0 )
        subfolder = state.subfolder
        os.makedirs(subfolder, exist_ok=True)

        xyz_path = os.path.join(subfolder, "initialGeometry.xyz")

        if state.initial_xyz and state.initial_xyz not in ("Random", "None"):
            # User-supplied geometry
            shutil.copy2(state.initial_xyz, xyz_path)
        elif state.smiles:
            # Validate SMILES before attempting conformer generation
            from rdkit import Chem
            test_mol = Chem.MolFromSmiles(state.smiles)
            if test_mol is None:
                raise RuntimeError(
                    f"Invalid SMILES string: '{state.smiles}'. "
                    "RDKit cannot parse this molecule. "
                    "Please check the identifier or provide a valid SMILES."
                )
            del test_mol

            # Use the selected tautomer SMILES when available
            smiles_for_conf = state.selected_tautomer or state.smiles

            # RDKit conformer generation
            molecule = rdk.generateConformer(
                smiles_for_conf,
                xyzPath=xyz_path,
                numConformers=state.num_conformers,
            )
            if state.charge is None:
                state.resolved_charge = rdmolops.GetFormalCharge(molecule)
                state.charge = state.resolved_charge
                state.save()
        else:
            raise RuntimeError(
                "Cannot generate conformer: no SMILES and no initial XYZ."
            )

        state.mark_step("conformer", STATUS_DONE)

    except Exception as exc:
        state.mark_step("conformer", STATUS_ERROR, error=str(exc))
        raise


# ---------------------------------------------------------------------------
# Step 3 – NWChem (launches Docker container)
# ---------------------------------------------------------------------------

def _nwchem_input_only(state: JobState) -> str:
    """Build the NWChem input file on the host and return its path."""
    subfolder = state.subfolder
    os.makedirs(subfolder, exist_ok=True)

    xyz_path = os.path.join(subfolder, "initialGeometry.xyz")
    input_path = os.path.join(subfolder, "input.nw")
    name = os.path.basename(subfolder)

    # Build config name from base + optional suffixes
    config_name = state.config
    if state.noautoz:
        config_name += "_noautoz"
    if state.iodine:
        config_name += "_Iodine"

    config_path = os.path.join(
        _REPO_ROOT, "Python", "lib", "_config", f"{config_name}.config"
    )
    if not os.path.isfile(config_path):
        raise FileNotFoundError(
            f"NWChem config not found: {config_path}. "
            f"Check that the combination base='{state.config}', "
            f"noautoz={state.noautoz}, iodine={state.iodine} is valid."
        )

    charge = state.charge if state.charge is not None else 0
    nwc.buildInputFile(input_path, config_path, xyz_path, name, charge)
    return input_path


def step_nwchem_launch(state: JobState) -> str:
    """
    Launch NWChem inside a detached Docker container.

    Returns the container ID (also saved in ``state``).
    """
    state.mark_step("nwchem", STATUS_RUNNING)

    try:
        # Build the input file on the host first
        _nwchem_input_only(state)

        # Mount the subfolder (containing input.nw + initialGeometry.xyz)
        container_id = docker_runner.launch_nwchem(
            job_subfolder=state.subfolder,
            nslots=state.nslots,
            container_name=f"spgen_{state.job_id}",
        )
        state.docker_container_id = container_id
        state.save()
        return container_id

    except Exception as exc:
        state.mark_step("nwchem", STATUS_ERROR, error=str(exc))
        raise


def step_nwchem_poll(state: JobState) -> dict:
    """
    Check the running NWChem container.

    Returns a progress dict (see ``docker_runner.parse_nwchem_progress``).
    If the container has exited, marks the step done/error and returns.
    """
    cid = state.docker_container_id
    if not cid:
        return {"phase": "not_started"}

    status = docker_runner.get_status(cid)

    if status == "running":
        progress = docker_runner.parse_nwchem_progress(state.output_nw_path)
        # Persist the detected sub-phase so it survives page reloads
        detected = progress.get("phase", "unknown")
        if detected in ("vacuum_opt", "cosmo_opt") and state.nwchem_phase != detected:
            state.nwchem_phase = detected
            state.save()
        return progress

    if status == "exited":
        exit_code = docker_runner.get_exit_code(cid)
        if exit_code == 0:
            state.nwchem_phase = "finished"
            state.mark_step("nwchem", STATUS_DONE)
            return {"phase": "finished", "exit_code": 0}
        else:
            logs_tail = docker_runner.get_logs(cid, tail=30)
            state.nwchem_phase = "error"
            state.mark_step(
                "nwchem", STATUS_ERROR,
                error=f"Container exited with code {exit_code}\n{logs_tail}",
            )
            return {"phase": "error", "exit_code": exit_code, "logs": logs_tail}

    return {"phase": status}


# ---------------------------------------------------------------------------
# Step 4 – Parse NWChem results
# ---------------------------------------------------------------------------

def step_parse(state: JobState) -> dict:
    """
    Parse NWChem output files and generate finalGeometry.xyz + outputSummary.

    Returns a dict of parsed data for display:
        converged, surface_area, n_segments, atom_coords
    """
    state.mark_step("parse", STATUS_RUNNING)
    subfolder = state.subfolder
    name = state.nwchem_name

    try:
        output_path = os.path.join(subfolder, "output.nw")

        # Check convergence — gate COSMO reads on success
        converged = nwc.checkConvergence(output_path)
        if converged == -1:
            raise RuntimeError(
                "NWChem failed to converge in vacuum geometry optimisation. "
                "Check output.nw for details."
            )
        if converged == 0:
            raise RuntimeError(
                "NWChem failed to converge in COSMO solvation optimisation. "
                "Check output.nw for details."
            )

        # Read COSMO
        cosmo_path = os.path.join(subfolder, f"{name}.cosmo.xyz")
        seg_coords, seg_charges = nwc.readCOSMO(cosmo_path)

        # Read output
        surface_area, seg_areas, atom_coords, seg_atoms = nwc.readOutput(output_path, True)

        # Save parsed data as numpy files so step_sigma can re-use them
        np_dir = os.path.join(subfolder, "_parsed")
        os.makedirs(np_dir, exist_ok=True)
        numpy.save(os.path.join(np_dir, "seg_coords.npy"), seg_coords)
        numpy.save(os.path.join(np_dir, "seg_charges.npy"), seg_charges)
        numpy.save(os.path.join(np_dir, "seg_areas.npy"), seg_areas)
        numpy.save(os.path.join(np_dir, "seg_atoms.npy"), seg_atoms)
        numpy.save(os.path.join(np_dir, "atom_coords.npy"), numpy.array(atom_coords, dtype=object))
        with open(os.path.join(np_dir, "surface_area.txt"), "w") as f:
            f.write(str(surface_area))

        # Generate final XYZ
        nwc.generateFinalXYZ(atom_coords, os.path.join(subfolder, "finalGeometry.xyz"))

        # Generate output summary
        nwc.generateLastStep(output_path, os.path.join(subfolder, "outputSummary.nw"))

        state.mark_step("parse", STATUS_DONE)

        return {
            "converged": converged,
            "surface_area": surface_area,
            "n_segments": len(seg_charges),
            "n_atoms": len(atom_coords),
        }

    except Exception as exc:
        state.mark_step("parse", STATUS_ERROR, error=str(exc))
        raise


# ---------------------------------------------------------------------------
# Step 5 – Sigma surface + profile
# ---------------------------------------------------------------------------

def step_sigma(state: JobState) -> dict:
    """
    Compute sigma surface matrix and histogram sigma profile.

    Returns a dict with sigma and sigmaProfile arrays for plotting.
    """
    state.mark_step("sigma", STATUS_RUNNING)
    subfolder = state.subfolder

    try:
        np_dir = os.path.join(subfolder, "_parsed")

        seg_coords = numpy.load(os.path.join(np_dir, "seg_coords.npy"), allow_pickle=True).tolist()
        seg_charges = numpy.load(os.path.join(np_dir, "seg_charges.npy"), allow_pickle=True).tolist()
        seg_areas = numpy.load(os.path.join(np_dir, "seg_areas.npy"), allow_pickle=True).tolist()
        seg_atoms = numpy.load(os.path.join(np_dir, "seg_atoms.npy"), allow_pickle=True).tolist()
        with open(os.path.join(np_dir, "surface_area.txt")) as f:
            surface_area = float(f.read().strip())

        avg_radius = state.avg_radius  # None → getSigmaMatrix skips averaging
        sigma_bins = state.sigma_bins

        log_path = os.path.join(state.job_dir, "job.log")

        sigma_matrix, avg_sigma_matrix = sp.getSigmaMatrix(
            seg_coords, seg_charges, seg_areas, surface_area, seg_atoms,
            avgRadius=avg_radius, logPath=log_path,
        )

        # Save sigma surface
        sp_path = os.path.join(subfolder, "sigmaSurface.csv")
        numpy.savetxt(sp_path, sigma_matrix, delimiter=",")

        # Get sigma profile
        sigma, sigma_profile = sp.getSigmaProfile(avg_sigma_matrix, sigma_bins)

        # Save sigma profile
        sp_path = os.path.join(subfolder, "sigmaProfile.csv")
        numpy.savetxt(sp_path, numpy.column_stack((sigma, sigma_profile)), delimiter=",")

        state.mark_step("sigma", STATUS_DONE)

        return {
            "sigma": sigma.tolist(),
            "sigma_profile": sigma_profile.tolist(),
        }

    except Exception as exc:
        state.mark_step("sigma", STATUS_ERROR, error=str(exc))
        raise


# ---------------------------------------------------------------------------
# Convenience: run all steps autonomously
# ---------------------------------------------------------------------------

def run_all(state: JobState, poll_interval: float = 5.0):
    """
    Execute every remaining step in order.

    Blocks during the NWChem Docker phase, polling every *poll_interval* seconds.
    Yields (step_name, status_dict) tuples for progress reporting.
    """
    # Step 1
    if state.step_status["resolve"] not in (STATUS_DONE, STATUS_SKIPPED):
        step_resolve(state)
    yield ("resolve", {"status": state.step_status["resolve"]})

    # Step 2
    if state.step_status["conformer"] not in (STATUS_DONE, STATUS_SKIPPED):
        step_conformer(state)
    yield ("conformer", {"status": state.step_status["conformer"]})

    # Step 3
    if state.step_status["nwchem"] not in (STATUS_DONE, STATUS_SKIPPED):
        step_nwchem_launch(state)
        while True:
            progress = step_nwchem_poll(state)
            yield ("nwchem", progress)
            if progress.get("phase") in ("finished", "error"):
                break
            time.sleep(poll_interval)
    else:
        yield ("nwchem", {"status": state.step_status["nwchem"]})

    if state.step_status["nwchem"] == STATUS_ERROR:
        return

    # Step 4
    if state.step_status["parse"] not in (STATUS_DONE, STATUS_SKIPPED):
        result = step_parse(state)
        yield ("parse", result)
    else:
        yield ("parse", {"status": state.step_status["parse"]})

    # Step 5
    if state.step_status["sigma"] not in (STATUS_DONE, STATUS_SKIPPED):
        result = step_sigma(state)
        yield ("sigma", result)
    else:
        yield ("sigma", {"status": state.step_status["sigma"]})
