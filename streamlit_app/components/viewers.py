"""
3-D molecular viewer and sigma-profile plotting components.
"""

import os
import streamlit as st
import numpy as np

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

try:
    import py3Dmol
    HAS_3D = True
except ImportError:
    HAS_3D = False

from job_state import JobState


# ---------------------------------------------------------------------------
# 3-D molecule viewer
# ---------------------------------------------------------------------------

def _render_py3dmol(xyz_data: str, width: int = 600, height: int = 450):
    """
    Render an XYZ string as an interactive 3-D viewer using py3Dmol,
    embedded via ``st.components.v1.html`` (works reliably in Docker).
    """
    viewer = py3Dmol.view(width=width, height=height)
    viewer.addModel(xyz_data, "xyz")
    viewer.setStyle({"stick": {"radius": 0.15}, "sphere": {"scale": 0.25}})
    viewer.setBackgroundColor(0xeeeeee)
    viewer.zoomTo()
    viewer.render()

    # Extract the self-contained HTML/JS snippet
    t = viewer.js()
    html = t.startjs + t.endjs
    st.components.v1.html(html, width=width, height=height, scrolling=False)


def render_3d_viewer(state: JobState, which: str = "final"):
    """
    Render a 3-D interactive viewer of the molecule.

    ``which`` can be ``'initial'`` or ``'final'``.
    """
    path = (
        state.final_geometry_path if which == "final" else state.initial_geometry_path
    )
    if not os.path.isfile(path):
        st.info(f"No {which} geometry available yet.")
        return

    with open(path) as f:
        xyz_data = f.read()

    if HAS_3D:
        _render_py3dmol(xyz_data)
    else:
        st.warning("Install `py3Dmol` for interactive 3-D viewing.")
        st.code(xyz_data, language="text")


def render_xyz_download(state: JobState, which: str = "final"):
    """Offer a download button for the XYZ file."""
    path = (
        state.final_geometry_path if which == "final" else state.initial_geometry_path
    )
    if os.path.isfile(path):
        with open(path) as f:
            data = f.read()
        label = f"Download {which} geometry (.xyz)"
        st.download_button(label, data, file_name=f"{state.name}_{which}.xyz")


# ---------------------------------------------------------------------------
# Sigma profile plot
# ---------------------------------------------------------------------------

def render_sigma_profile(state: JobState):
    """Plot the sigma profile from sigmaProfile.csv."""
    sp_path = state.sigma_profile_path
    if not os.path.isfile(sp_path):
        st.info("No sigma profile computed yet.")
        return

    data = np.loadtxt(sp_path, delimiter=",")
    sigma = data[:, 0]
    profile = data[:, 1]

    if HAS_PLOTLY:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=sigma,
                y=profile,
                mode="lines",
                name=state.name,
                line=dict(width=2),
            )
        )
        fig.update_layout(
            title=f"Sigma Profile — {state.name}",
            xaxis_title="σ (e/Å²)",
            yaxis_title="p(σ) (Å²)",
            template="plotly_white",
            height=450,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.line_chart({"sigma": sigma, "profile": profile})

    # Download button
    st.download_button(
        "Download sigmaProfile.csv",
        open(sp_path).read(),
        file_name=f"{state.name}_sigmaProfile.csv",
        mime="text/csv",
    )


def render_sigma_surface(state: JobState):
    """Plot sigma surface charge-density histogram from sigmaSurface.csv."""
    ss_path = state.sigma_surface_path
    if not os.path.isfile(ss_path):
        st.info("No sigma surface computed yet.")
        return

    data = np.loadtxt(ss_path, delimiter=",")
    # data columns: x, y, z, charge, area, sigma, atom_idx
    sigma_vals = data[:, 5]

    if HAS_PLOTLY:
        fig = go.Figure()
        fig.add_trace(
            go.Histogram(
                x=sigma_vals,
                nbinsx=100,
                name="σ distribution",
            )
        )
        fig.update_layout(
            title=f"Sigma Surface Distribution — {state.name}",
            xaxis_title="σ (e/Å²)",
            yaxis_title="Count",
            template="plotly_white",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.download_button(
        "Download sigmaSurface.csv",
        open(ss_path).read(),
        file_name=f"{state.name}_sigmaSurface.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------
# SCF convergence plot
# ---------------------------------------------------------------------------

def render_scf_convergence(state: JobState):
    """Plot DFT energy vs optimisation step from output.nw."""
    from components.step_viewer import parse_output_nw_for_scf

    records = parse_output_nw_for_scf(state.output_nw_path)
    if not records:
        st.info("No SCF convergence data yet.")
        return

    steps = [r["step"] for r in records]
    energies = [r["energy"] for r in records]

    if HAS_PLOTLY:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(x=list(range(len(energies))), y=energies, mode="lines+markers", name="Energy")
        )
        fig.update_layout(
            title="DFT Energy Convergence",
            xaxis_title="SCF Evaluation",
            yaxis_title="Total DFT Energy (Ha)",
            template="plotly_white",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.line_chart(energies)
