"""
Step-progress stepper and NWChem live monitor panel.
"""

import streamlit as st
import os
import re

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

from job_state import STEPS, STEP_LABELS, STATUS_PENDING, STATUS_RUNNING, STATUS_DONE, STATUS_ERROR, STATUS_SKIPPED, JobState


_STATUS_ICONS = {
    STATUS_PENDING: "⬜",
    STATUS_RUNNING: "🔄",
    STATUS_DONE: "✅",
    STATUS_ERROR: "❌",
    STATUS_SKIPPED: "⏭️",
}


# NWChem sub-phase definitions (order matters)
_NWCHEM_SUBPHASES = [
    ("vacuum_opt", "3a. Vacuum Optimisation"),
    ("cosmo_opt",  "3b. COSMO Optimisation"),
]


def _subphase_icon(subphase_key: str, current_phase: str) -> str:
    """Return a status icon for a NWChem sub-phase given the current live phase."""
    order = ["not_started", "vacuum_opt", "cosmo_opt", "finished"]
    try:
        current_idx = order.index(current_phase)
    except ValueError:
        # error or unknown
        current_idx = -1
    sub_idx = order.index(subphase_key)

    if current_phase == "error":
        # Mark the phase that was active as errored, earlier ones as done
        return "❌"  # simplified — shown in the sub-stepper
    if current_idx > sub_idx:
        return "✅"
    if current_idx == sub_idx:
        return "🔄"
    return "⬜"


def _resolve_nwchem_phase(state: JobState, progress: dict | None = None) -> str:
    """Pick the best-known NWChem sub-phase from live progress or persisted state."""
    if progress and progress.get("phase") in ("vacuum_opt", "cosmo_opt", "finished", "error"):
        return progress["phase"]
    return getattr(state, "nwchem_phase", "not_started")


def render_step_progress(state: JobState):
    """Render a horizontal step-progress bar."""
    cols = st.columns(len(STEPS))
    for col, step in zip(cols, STEPS):
        status = state.step_status.get(step, STATUS_PENDING)
        icon = _STATUS_ICONS.get(status, "⬜")
        label = STEP_LABELS[step]

        # Build optional sub-phase annotation for the NWChem step
        sub_html = ""
        if step == "nwchem" and status in (STATUS_RUNNING, STATUS_DONE, STATUS_ERROR):
            phase = _resolve_nwchem_phase(state)
            parts = []
            for key, short_label in _NWCHEM_SUBPHASES:
                si = _subphase_icon(key, phase)
                parts.append(f"{si} {short_label}")
            sub_html = "<br>".join(parts)
            sub_html = f"<div style='margin-top:2px; font-size:0.75em; line-height:1.4'>{sub_html}</div>"

        col.markdown(
            f"<div style='text-align:center'>"
            f"<span style='font-size:1.6em'>{icon}</span><br>"
            f"<small>{label}</small>"
            f"{sub_html}"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_nwchem_substeps(state: JobState, progress: dict | None = None):
    """
    Render a two-item sub-stepper showing Vacuum and COSMO phases.

    Displayed inside the NWChem expander to disclose the two sequential
    DFT optimisation phases up front.
    """
    phase = _resolve_nwchem_phase(state, progress)

    cols = st.columns(2)
    for col, (key, label) in zip(cols, _NWCHEM_SUBPHASES):
        icon = _subphase_icon(key, phase)
        col.markdown(
            f"<div style='text-align:center; padding:6px 0;'>"
            f"<span style='font-size:1.3em'>{icon}</span><br>"
            f"<small><b>{label}</b></small>"
            f"</div>",
            unsafe_allow_html=True,
        )


def render_nwchem_monitor(state: JobState, progress: dict | None = None, key_suffix: str = ""):
    """
    Render live NWChem progress info with SCF convergence charts.

    ``progress`` is the dict returned by ``docker_runner.parse_nwchem_progress``
    or ``pipeline.step_nwchem_poll``.
    """
    if progress is None:
        progress = {}

    phase = progress.get("phase", "unknown")
    phase_label = {
        "vacuum_opt": "Vacuum geometry optimisation",
        "cosmo_opt": "COSMO solvation optimisation",
        "finished": "Complete",
        "error": "Error",
        "not_started": "Not started",
        "unknown": "Initialising…",
    }.get(phase, phase)

    st.markdown(f"**Phase:** {phase_label}")

    col1, col2, col3 = st.columns(3)
    step = progress.get("step")
    energy = progress.get("energy")
    walltime = progress.get("walltime_s")

    col1.metric("Opt Step", step if step is not None else "—")
    col2.metric("DFT Energy (Ha)", f"{energy:.8f}" if energy is not None else "—")
    col3.metric("Wall Time", f"{walltime:.0f}s" if walltime is not None else "—")

    if progress.get("converged"):
        st.success("Optimisation converged!")

    if phase == "error":
        st.error(progress.get("logs", "Unknown error"))

    # ----- Live charts from output.nw -----
    render_live_charts(state, key_suffix=key_suffix)


def render_live_charts(state: JobState, key_suffix: str = ""):
    """Parse output.nw and render SCF + geometry-opt convergence charts."""
    scf_records, step_records = parse_output_nw_full(state.output_nw_path)

    if not scf_records and not step_records:
        return

    if HAS_PLOTLY:
        # --- SCF convergence (energy & delta-E per iteration, side-by-side) ---
        if scf_records:
            fig = make_subplots(
                rows=1, cols=2,
                horizontal_spacing=0.10,
                subplot_titles=("SCF Energy per Iteration", "SCF |ΔE| per Iteration"),
            )

            # Group by opt step for colour coding
            steps_seen = sorted(set(r["opt_step"] for r in scf_records))
            for opt_step in steps_seen:
                subset = [r for r in scf_records if r["opt_step"] == opt_step]
                iters = [r["global_idx"] for r in subset]
                energies = [r["energy"] for r in subset]
                deltas = [abs(r["delta_e"]) if r["delta_e"] is not None else None for r in subset]

                phase_tag = "COSMO" if subset[0].get("cosmo") else "Vacuum"
                label = f"{phase_tag} Step {opt_step}"

                fig.add_trace(
                    go.Scatter(x=iters, y=energies, mode="lines+markers",
                               name=label, marker=dict(size=4),
                               showlegend=True),
                    row=1, col=1,
                )
                fig.add_trace(
                    go.Scatter(x=iters, y=deltas, mode="lines+markers",
                               name=label, marker=dict(size=4),
                               showlegend=False),
                    row=1, col=2,
                )

            fig.update_yaxes(title_text="Energy (Ha)", row=1, col=1)
            fig.update_yaxes(title_text="|ΔE| (Ha)", type="log", row=1, col=2)
            fig.update_xaxes(title_text="SCF Iteration (global)", row=1, col=1)
            fig.update_xaxes(title_text="SCF Iteration (global)", row=1, col=2)
            fig.update_layout(height=380, template="plotly_white",
                              margin=dict(t=40, b=30))
            st.plotly_chart(fig, use_container_width=True, key=f"scf_chart{key_suffix}")

    else:
        # Fallback: plain text summary
        if scf_records:
            st.caption(f"SCF iterations so far: {len(scf_records)}")


def render_output_nw_tail(state: JobState, n_lines: int = 30):
    """Show the last N lines of output.nw if it exists."""
    output_path = state.output_nw_path
    if not os.path.isfile(output_path):
        st.info("No output.nw file yet.")
        return

    with open(output_path) as f:
        lines = f.readlines()

    tail = lines[-n_lines:] if len(lines) > n_lines else lines
    st.code("".join(tail), language="text")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_SCF_RE = re.compile(
    r"d=\s*\d+,ls=[\d.]+,diis\s+(\d+)\s+([-\d.DE+]+)\s+([-\d.DE+]+)\s+([-\d.DE+]+)\s+([-\d.DE+]+)\s+([\d.]+)"
)
_STEP_RE = re.compile(r"^\s+Step\s+(\d+)")
_AT_RE = re.compile(
    r"^@\s+(\d+)\s+([-\d.]+)\s+([-\d.DE+]+)\s+([-\d.DE+]+)\s+([-\d.DE+]+)\s+([-\d.DE+]+)\s+([-\d.DE+]+)\s+([\d.]+)"
)


def _fortran_float(s: str) -> float:
    """Convert Fortran-style '1.23D-04' to Python float."""
    return float(s.replace("D", "E").replace("d", "e"))


def parse_output_nw_full(output_path: str) -> tuple[list[dict], list[dict]]:
    """
    Parse output.nw for SCF iteration data and geometry-opt step summaries.

    Returns
    -------
    scf_records : list of dict
        Keys: opt_step, iter, energy, delta_e, rms_dens, diis_err, time, cosmo, global_idx
    step_records : list of dict
        Keys: step, energy, delta_e, gmax, grms, xrms, xmax, walltime
    """
    scf_records: list[dict] = []
    step_records: list[dict] = []

    if not os.path.isfile(output_path):
        return scf_records, step_records

    current_step = 0
    in_cosmo = False
    global_idx = 0

    try:
        with open(output_path) as f:
            for line in f:
                # Detect phase switch
                if "-cosmo- solvent" in line:
                    in_cosmo = True

                # Opt step header
                m = _STEP_RE.search(line)
                if m and "@" not in line:
                    current_step = int(m.group(1))

                # SCF iteration line
                m = _SCF_RE.search(line)
                if m:
                    scf_records.append({
                        "opt_step": current_step,
                        "iter": int(m.group(1)),
                        "energy": _fortran_float(m.group(2)),
                        "delta_e": _fortran_float(m.group(3)),
                        "rms_dens": _fortran_float(m.group(4)),
                        "diis_err": _fortran_float(m.group(5)),
                        "time": float(m.group(6)),
                        "cosmo": in_cosmo,
                        "global_idx": global_idx,
                    })
                    global_idx += 1

                # @ step summary line
                m = _AT_RE.match(line)
                if m:
                    step_records.append({
                        "step": int(m.group(1)),
                        "energy": float(m.group(2)),
                        "delta_e": _fortran_float(m.group(3)),
                        "gmax": _fortran_float(m.group(4)),
                        "grms": _fortran_float(m.group(5)),
                        "xrms": _fortran_float(m.group(6)),
                        "xmax": _fortran_float(m.group(7)),
                        "walltime": float(m.group(8)),
                    })

    except Exception:
        pass

    return scf_records, step_records


def parse_output_nw_for_scf(output_path: str) -> list[dict]:
    """
    Legacy helper — returns a flat list of {step, energy} dicts.
    Used by ``viewers.render_scf_convergence``.
    """
    scf_records, _ = parse_output_nw_full(output_path)
    return [{"step": r["opt_step"], "energy": r["energy"]} for r in scf_records]
