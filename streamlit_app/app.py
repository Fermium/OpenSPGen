"""
OpenSPGen-App — Interactive Sigma Profile Generator
====================================================

Streamlit application that orchestrates the full sigma-profile pipeline:

    1. Identifier Resolution  →  SMILES via CIRpy + PubChemPy
    2. Conformer Generation   →  RDKit MMFF
    3. NWChem DFT + COSMO     →  Docker container (detached)
    4. Parse NWChem Output    →  convergence check, final geometry
    5. Sigma Profile          →  surface matrix + histogram

Usage
-----
    streamlit run streamlit_app/app.py
"""

import os
import sys
import time
import tempfile

import streamlit as st

# ---------------------------------------------------------------------------
# Add the streamlit_app directory to sys.path so local imports work
# regardless of the working directory when `streamlit run` is invoked.
# ---------------------------------------------------------------------------
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

import job_state as js
import pipeline
import docker_runner
from components.molecule_input import render_molecule_input
from components.step_viewer import render_step_progress, render_nwchem_substeps, render_nwchem_monitor, render_output_nw_tail
from job_state import STEP_LABELS
from components.viewers import (
    render_3d_viewer,
    render_xyz_download,
    render_sigma_profile,
    render_sigma_surface,
    render_scf_convergence,
)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="OpenSPGen-App",
    page_icon="🧪",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
if "active_job_id" not in st.session_state:
    st.session_state.active_job_id = None
if "auto_run" not in st.session_state:
    st.session_state.auto_run = False

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🧪 OpenSPGen-App")
    st.caption("Interactive Sigma Profile Generator")
    st.divider()

    # --- New job form ---
    inputs = render_molecule_input()
    if inputs is not None:
        # Save uploaded XYZ to a temp file if provided
        xyz_path = None
        if inputs["initial_xyz_bytes"] is not None:
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".xyz", dir=tempfile.gettempdir()
            )
            tmp.write(inputs["initial_xyz_bytes"].getvalue())
            tmp.close()
            xyz_path = tmp.name

        state = js.create_job(
            identifier=inputs["identifier"],
            identifier_type=inputs["identifier_type"],
            name=inputs["name"],
            charge=inputs["charge"],
            nslots=inputs["nslots"],
            noautoz=inputs["noautoz"],
            iodine=inputs["iodine"],
            initial_xyz=xyz_path,
            avg_radius=inputs["avg_radius"],
        )
        st.session_state.active_job_id = state.job_id
        st.success(f"Job **{state.job_id}** created!")
        st.rerun()

# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------

active_id = st.session_state.active_job_id
if active_id is None:
    st.markdown(
        "## Welcome to OpenSPGen-App\n\n"
        "Use the sidebar to create a new sigma-profile job, or select an "
        "existing job from the history.\n\n"
        "**Pipeline steps:**\n"
        "1. Identifier Resolution\n"
        "2. Conformer Generation\n"
        "3. NWChem DFT + COSMO (Docker)\n"
        "   - a. Vacuum geometry optimisation\n"
        "   - b. COSMO solvation optimisation\n"
        "4. Parse NWChem Output\n"
        "5. Sigma Profile Computation\n"
    )
    st.stop()

# Load the active job
try:
    state = js.JobState.load(os.path.join(js.JOBS_ROOT, active_id))
except FileNotFoundError:
    st.error(f"Job directory not found: {active_id}")
    st.session_state.active_job_id = None
    st.stop()

# Header
st.markdown(f"## Job: {state.name}")
st.caption(f"ID: `{state.job_id}` — Created: {state.created_at} — Config: {state.config}")

# Step progress bar
render_step_progress(state)
st.divider()

# ---------------------------------------------------------------------------
# Action buttons
# ---------------------------------------------------------------------------
col_run, col_next, col_stop = st.columns([1, 1, 1])

with col_run:
    if st.button("▶️ Run All Remaining Steps", use_container_width=True, type="primary"):
        st.session_state.auto_run = True
        st.rerun()

with col_next:
    next_step = state.next_pending_step()
    _label = f"⏭️ Run Next: {STEP_LABELS[next_step]}" if next_step else "All done"
    if st.button(_label, use_container_width=True, disabled=next_step is None):
        st.session_state.run_single_step = next_step
        st.rerun()

with col_stop:
    _handle = state.docker_container_id
    if _handle and docker_runner.get_status(_handle) == "running":
        if st.button("⏹️ Stop NWChem", use_container_width=True):
            docker_runner.stop_and_remove(_handle)
            state.mark_step("nwchem", js.STATUS_ERROR, error="Stopped by user")
            st.rerun()

# ---------------------------------------------------------------------------
# Auto-run mode
# ---------------------------------------------------------------------------
if st.session_state.get("auto_run"):
    st.session_state.auto_run = False
    progress_placeholder = st.empty()
    poll_counter = 0

    for step_name, result in pipeline.run_all(state, poll_interval=10.0):
        progress_placeholder.empty()
        with progress_placeholder.container():
            render_step_progress(state)
            st.markdown(f"**Running:** {STEP_LABELS[step_name]}")
            if step_name == "nwchem" and isinstance(result, dict) and "phase" in result:
                render_nwchem_substeps(state, result)
                render_nwchem_monitor(state, result, key_suffix=f"_autorun_{poll_counter}")
        poll_counter += 1

    st.rerun()

# ---------------------------------------------------------------------------
# Single step execution
# ---------------------------------------------------------------------------
single_step = st.session_state.pop("run_single_step", None)
if single_step:
    try:
        if single_step == "resolve":
            pipeline.step_resolve(state)
        elif single_step == "conformer":
            pipeline.step_conformer(state)
        elif single_step == "nwchem":
            pipeline.step_nwchem_launch(state)
        elif single_step == "parse":
            pipeline.step_parse(state)
        elif single_step == "sigma":
            pipeline.step_sigma(state)
        st.rerun()
    except Exception as exc:
        st.error(f"Step **{single_step}** failed: {exc}")

# ---------------------------------------------------------------------------
# Step detail panels
# ---------------------------------------------------------------------------

# Step 1: Resolve
with st.expander("1. Identifier Resolution", expanded=state.current_step == "resolve"):
    st.markdown(f"**Identifier:** {state.identifier} ({state.identifier_type})")
    if state.smiles:
        st.markdown(f"**SMILES:** `{state.smiles}`")
        # 2-D structure from RDKit
        try:
            from rdkit import Chem
            from rdkit.Chem import Draw
            mol = Chem.MolFromSmiles(state.smiles)
            if mol is not None:
                img = Draw.MolToImage(mol, size=(400, 300))
                st.image(img, caption=state.name)
        except Exception:
            pass
    if state.resolved_charge is not None:
        st.markdown(f"**Charge:** {state.resolved_charge}")
    if state.cross_check_warning:
        st.warning(state.cross_check_warning)

# Step 2: Conformer
with st.expander("2. Conformer Generation", expanded=state.current_step == "conformer"):
    if state.step_status["conformer"] in (js.STATUS_DONE, js.STATUS_SKIPPED):
        tab_init, tab_final = st.tabs(["Initial Geometry", "Final Geometry"])
        with tab_init:
            render_3d_viewer(state, which="initial")
            render_xyz_download(state, which="initial")
    else:
        st.info("Conformer not yet generated.")

# Step 3: NWChem
with st.expander("3. NWChem DFT + COSMO", expanded=state.current_step == "nwchem"):
    handle = state.docker_container_id
    if handle:
        status = docker_runner.get_status(handle)
        short_id = handle[:12]
        st.markdown(f"**Docker container:** `{short_id}` — Status: **{status}**")

        if status == "running":
            progress = docker_runner.parse_nwchem_progress(state.output_nw_path)
            # Persist detected phase for the stepper bar / page reloads
            detected = progress.get("phase", "unknown")
            if detected in ("vacuum_opt", "cosmo_opt") and state.nwchem_phase != detected:
                state.nwchem_phase = detected
                state.save()
            render_nwchem_substeps(state, progress)
            render_nwchem_monitor(state, progress, key_suffix="_step3")
            render_scf_convergence(state)
            st.markdown("*Auto-refreshes every 15 seconds…*")
            time.sleep(15)
            st.rerun()
        elif status == "exited":
            exit_code = docker_runner.get_exit_code(handle)
            if exit_code == 0 or exit_code is None:
                if state.nwchem_phase != "finished":
                    state.nwchem_phase = "finished"
                st.success("NWChem completed successfully!")
                if state.step_status["nwchem"] != js.STATUS_DONE:
                    state.mark_step("nwchem", js.STATUS_DONE)
            else:
                state.nwchem_phase = "error"
                st.error(f"NWChem exited with code {exit_code}")
                logs = docker_runner.get_logs(handle, tail=50)
                st.code(logs, language="text")
            render_nwchem_substeps(state)
    else:
        # Show sub-steps even before NWChem starts, so user knows what's coming
        render_nwchem_substeps(state)
        st.info("NWChem not started yet.")

    # Show output.nw tail
    if os.path.isfile(state.output_nw_path):
        with st.popover("View output.nw tail"):
            render_output_nw_tail(state, n_lines=50)

# Step 4: Parse
with st.expander("4. Parse Results", expanded=state.current_step == "parse"):
    if state.step_status["parse"] == js.STATUS_DONE:
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Final Geometry**")
            render_3d_viewer(state, which="final")
            render_xyz_download(state, which="final")
        with col_b:
            st.markdown("**SCF Convergence**")
            render_scf_convergence(state)
    else:
        st.info("Waiting for NWChem to complete before parsing.")

# Step 5: Sigma Profile
with st.expander("5. Sigma Profile", expanded=state.current_step == "sigma"):
    if state.step_status["sigma"] == js.STATUS_DONE:
        tab_profile, tab_surface = st.tabs(["Sigma Profile", "Sigma Surface"])
        with tab_profile:
            render_sigma_profile(state)
        with tab_surface:
            render_sigma_surface(state)
    else:
        st.info("Sigma profile not yet computed.")

# ---------------------------------------------------------------------------
# Error display
# ---------------------------------------------------------------------------
if state.error:
    st.divider()
    st.error(f"**Last error:** {state.error}")

# ---------------------------------------------------------------------------
# Download all outputs as ZIP
# ---------------------------------------------------------------------------
if state.is_complete():
    st.divider()
    import io, zipfile

    def _build_zip(state: js.JobState) -> bytes:
        buf = io.BytesIO()
        sub = state.subfolder
        files_to_include = [
            ("sigmaProfile.csv", state.sigma_profile_path),
            ("sigmaSurface.csv", state.sigma_surface_path),
            ("finalGeometry.xyz", state.final_geometry_path),
            ("initialGeometry.xyz", state.initial_geometry_path),
            ("input.nw", state.input_nw_path),
            ("output.nw", state.output_nw_path),
            ("outputSummary.nw", os.path.join(sub, "outputSummary.nw")),
        ]
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, fpath in files_to_include:
                if os.path.isfile(fpath):
                    zf.write(fpath, arcname)
        return buf.getvalue()

    zip_bytes = _build_zip(state)
    st.download_button(
        "📦 Download all outputs (.zip)",
        data=zip_bytes,
        file_name=f"{state.name}_sigma_profile.zip",
        mime="application/zip",
        use_container_width=True,
    )

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.divider()
st.caption(
    "OpenSPGen-App — Sigma Profile Generator | "
    "NWChem 7.3.0 | BP86/def2-TZVP + COSMO"
)
