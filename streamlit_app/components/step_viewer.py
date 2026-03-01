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


# ---------------------------------------------------------------------------
# Inline SVG icon helpers (replace emoji for cross-platform consistency)
# ---------------------------------------------------------------------------

_STEPPER_CSS = """
<style>
@keyframes spg-spin {
    0%   { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
.spg-icon { display:inline-block; vertical-align:middle; }
.spg-icon-spin svg { animation: spg-spin 1s linear infinite; }
</style>
"""


def _svg_icon(body: str, *, size: int = 28, cls: str = "", color: str = "currentColor") -> str:
    """Wrap an SVG body in a sized <span> container."""
    extra = f" {cls}" if cls else ""
    return (
        f'<span class="spg-icon{extra}">'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f'{body}</svg></span>'
    )


def _icon_pending(size: int = 28) -> str:
    return _svg_icon('<circle cx="12" cy="12" r="9"/>', size=size, color="#9ca3af")


def _icon_running(size: int = 28) -> str:
    # Partial arc that spins via CSS
    return _svg_icon(
        '<circle cx="12" cy="12" r="9" stroke-dasharray="42" stroke-dashoffset="14"/>',
        size=size, cls="spg-icon-spin", color="#2563eb",
    )


def _icon_done(size: int = 28) -> str:
    return _svg_icon(
        '<circle cx="12" cy="12" r="9" fill="#16a34a" stroke="#16a34a"/>'
        '<path d="M8 12.5l2.5 2.5 5-5" stroke="#fff"/>',
        size=size, color="#16a34a",
    )


def _icon_error(size: int = 28) -> str:
    return _svg_icon(
        '<circle cx="12" cy="12" r="9" fill="#dc2626" stroke="#dc2626"/>'
        '<path d="M9 9l6 6M15 9l-6 6" stroke="#fff"/>',
        size=size, color="#dc2626",
    )


def _icon_skipped(size: int = 28) -> str:
    return _svg_icon(
        '<circle cx="12" cy="12" r="9" fill="#9ca3af" stroke="#9ca3af"/>'
        '<path d="M10 8l4 4-4 4" stroke="#fff" fill="none"/>'
        '<line x1="15" y1="8" x2="15" y2="16" stroke="#fff"/>',
        size=size, color="#9ca3af",
    )


_STATUS_ICON_FN = {
    STATUS_PENDING: _icon_pending,
    STATUS_RUNNING: _icon_running,
    STATUS_DONE:    _icon_done,
    STATUS_ERROR:   _icon_error,
    STATUS_SKIPPED: _icon_skipped,
}


def _status_icon(status: str, size: int = 28) -> str:
    """Return an inline-SVG icon string for a step status."""
    fn = _STATUS_ICON_FN.get(status, _icon_pending)
    return fn(size=size)


def _inject_stepper_css():
    """Inject the stepper CSS once per render cycle."""
    if not st.session_state.get("_spg_stepper_css_injected"):
        st.markdown(_STEPPER_CSS, unsafe_allow_html=True)
        st.session_state["_spg_stepper_css_injected"] = True


# NWChem sub-phase definitions (order matters)
_NWCHEM_SUBPHASES = [
    ("vacuum_opt", "3a. Vacuum Optimisation"),
    ("cosmo_opt",  "3b. COSMO Optimisation"),
]


def _subphase_icon(subphase_key: str, current_phase: str, size: int = 18) -> str:
    """Return an inline-SVG status icon for a NWChem sub-phase."""
    order = ["not_started", "vacuum_opt", "cosmo_opt", "finished"]
    try:
        current_idx = order.index(current_phase)
    except ValueError:
        current_idx = -1
    sub_idx = order.index(subphase_key)

    if current_phase == "error":
        return _icon_error(size=size)
    if current_idx > sub_idx:
        return _icon_done(size=size)
    if current_idx == sub_idx:
        return _icon_running(size=size)
    return _icon_pending(size=size)


def _resolve_nwchem_phase(state: JobState, progress: dict | None = None) -> str:
    """Pick the best-known NWChem sub-phase from live progress or persisted state."""
    if progress and progress.get("phase") in ("vacuum_opt", "cosmo_opt", "finished", "error"):
        return progress["phase"]
    return getattr(state, "nwchem_phase", "not_started")


def render_step_progress(state: JobState):
    """Render a horizontal step-progress bar with SVG icons."""
    _inject_stepper_css()

    cols = st.columns(len(STEPS))
    for col, step in zip(cols, STEPS):
        status = state.step_status.get(step, STATUS_PENDING)
        icon = _status_icon(status, size=28)
        label = STEP_LABELS[step]

        # Build optional sub-phase annotation for the NWChem step
        sub_html = ""
        if step == "nwchem" and status in (STATUS_RUNNING, STATUS_DONE, STATUS_ERROR):
            phase = _resolve_nwchem_phase(state)
            parts = []
            for key, short_label in _NWCHEM_SUBPHASES:
                si = _subphase_icon(key, phase, size=16)
                parts.append(f"{si} {short_label}")
            sub_html = "<br>".join(parts)
            sub_html = f"<div style='margin-top:2px; font-size:0.75em; line-height:1.4'>{sub_html}</div>"

        col.markdown(
            f"<div style='text-align:center'>"
            f"{icon}<br>"
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
    _inject_stepper_css()
    phase = _resolve_nwchem_phase(state, progress)

    cols = st.columns(2)
    for col, (key, label) in zip(cols, _NWCHEM_SUBPHASES):
        icon = _subphase_icon(key, phase, size=22)
        col.markdown(
            f"<div style='text-align:center; padding:6px 0;'>"
            f"{icon}<br>"
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
