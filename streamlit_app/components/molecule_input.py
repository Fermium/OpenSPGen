"""
Molecule input form component.
"""

import os

import streamlit as st
from typing import Optional

_DEFAULT_CORES = max(2, os.cpu_count() or 2)


def render_molecule_input() -> Optional[dict]:
    """
    Render the molecule input form in the sidebar.

    Returns a dict of inputs when the user clicks Submit, or None.
    """
    with st.form("molecule_input", clear_on_submit=False):
        st.subheader("Molecule Input")

        name = st.text_input(
            "Job Name",
            value="",
            help="A short label for this job (e.g. 'water', 'betaine')",
        )

        id_type = st.selectbox(
            "Identifier Type",
            ["SMILES", "CAS-Number", "InChI", "InChIKey"],
            index=0,
        )

        identifier = st.text_input(
            "Identifier",
            value="",
            help="The molecule identifier (SMILES string, CAS number, etc.)",
        )

        col1, col2 = st.columns(2)
        with col1:
            charge = st.number_input(
                "Charge", min_value=-10, max_value=10, value=0, step=1
            )
        with col2:
            nslots = st.number_input(
                "CPU Cores", min_value=2, max_value=64, value=_DEFAULT_CORES, step=1,
                help="Number of MPI ranks for NWChem (must be >= 2)",
            )

        initial_xyz = st.file_uploader(
            "Initial XYZ (optional)",
            type=["xyz"],
            help="Upload an XYZ file to skip conformer generation",
        )

        st.divider()

        st.caption("Advanced options")
        auto_charge = st.checkbox(
            "Auto-detect charge from SMILES", value=True,
            help="When checked, formal charge is determined automatically "
            "from the resolved SMILES. Uncheck to specify manually.",
        )

        avg_radius = st.number_input(
            "Averaging radius (Å)",
            min_value=0.0,
            max_value=5.0,
            value=0.5,
            step=0.1,
            help="Radius for the sigma-surface averaging algorithm. "
            "Set to 0 to skip averaging.",
        )

        submitted = st.form_submit_button("🚀 Create Job", use_container_width=True)

    if submitted:
        if not name.strip():
            st.error("Please provide a job name.")
            return None
        if not identifier.strip():
            st.error("Please provide a molecule identifier.")
            return None

        result = {
            "name": name.strip(),
            "identifier_type": id_type,
            "identifier": identifier.strip(),
            "charge": None if auto_charge else int(charge),
            "nslots": int(nslots),
            "noautoz": False,
            "iodine": False,
            "avg_radius": float(avg_radius) if avg_radius > 0 else None,
            "initial_xyz_bytes": initial_xyz,  # UploadedFile or None
        }
        return result

    return None
