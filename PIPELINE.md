# OpenSPGen Pipeline — Step-by-Step Explanation

This document describes every step that OpenSPGen executes when generating a sigma profile for a molecule, from the initial command-line invocation to the final `sigmaProfile.csv` file.

---

## Overview

```
User Input (CAS / SMILES / XYZ)
        │
        ▼
  ┌─────────────────────┐
  │  1. Identifier       │  CAS / InChI / InChIKey → SMILES
  │     Resolution       │  (PubChem + CIRpy cross-check)
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  2. Initial Geometry │  SMILES → 3D conformer (RDKit)
  │     Generation       │  + MMFF94 force field relaxation
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  3. Vacuum Geometry  │  NWChem DFT optimisation
  │     Optimisation     │  (BP86/def2-TZVP, iterative)
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  4. COSMO Solvation  │  NWChem DFT optimisation
  │     Optimisation     │  with conductor-like screening
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  5. Sigma Surface    │  Extract point charges, areas,
  │     Extraction       │  coordinates from COSMO output
  └────────┬────────────┘
           ▼
  ┌─────────────────────┐
  │  6. Sigma Profile    │  Bin charge densities into a
  │     Computation      │  histogram (σ-profile)
  └────────┬────────────┘
           ▼
     sigmaProfile.csv
```

---

## Step 1 — Identifier Resolution

**Code**: `spGenerator.py` → `crossCheck()` (line ~425)

**What it does**: Converts the user-provided molecule identifier (CAS number, InChI, InChIKey) into a canonical SMILES string. It queries two independent databases:

- **CIRpy** (NIH Chemical Identifier Resolver): resolves any identifier to SMILES
- **PubChemPy** (PubChem API): resolves CAS numbers (as "name"), InChI, or InChIKey to SMILES

Both results are canonicalised with RDKit and compared. If they match, the SMILES is accepted. If they disagree, a warning is logged and the PubChem result is preferred. If neither database returns a hit, the job fails with an error.

**When it's skipped**: If the user provides `--idtype SMILES` (the SMILES is used directly) or supplies both `--initialxyz` and `--charge` (no SMILES is needed at all).

**Output**: A SMILES string, e.g., `C[N+](C)(C)CC(=O)[O-]` for betaine.

---

## Step 2 — Initial Geometry Generation

**Code**: `RDKit_Wrapper.py` → `generateConformer()` (line ~42)

**What it does**: Converts the SMILES string into a 3D molecular geometry that NWChem can use as a starting point.

The algorithm:
1. **Distance geometry**: RDKit's `EmbedMolecule()` generates a rough 3D conformer from the SMILES connectivity. Uses a fixed random seed (default: 42) for reproducibility.
2. **MMFF94 minimisation**: The rough geometry is relaxed using the Merck Molecular Force Field (MMFF94) as implemented in RDKit. This fixes unrealistic bond lengths and angles. Up to 10⁶ minimisation steps are allowed.
3. **Redundancy**: Steps 1–2 are repeated three times (seeds 0, 1, 2) and the lowest-energy conformer is kept. This protects against rare bad convergence from distance geometry.

**When it's skipped**: If the user provides `--initialxyz /path/to/file.xyz` — the provided XYZ is simply copied to the job folder as `initialGeometry.xyz`.

**Output**: `initialGeometry.xyz` — a Cartesian coordinate file with atom types and positions (in Ångströms).

---

## Step 3 — Vacuum Geometry Optimisation

**Code**: `NWChem_Wrapper.py` → `buildInputFile()` + `runNWChem()`  
**Config**: `Python/lib/_config/COSMO_BP86_TZVP.config` (first `task` block)

**What it does**: Optimises the molecular geometry in vacuum using quantum mechanics (DFT). This is the first of two NWChem computation phases.

**NWChem settings** (from the config file):
- **Method**: DFT with the BP86 functional (Becke88 exchange + Perdew86 correlation)
- **Basis set**: def2-TZVP (triple-zeta valence polarised — a large, accurate basis set)
- **Geometry optimiser**: NWChem's `driver` module — iteratively adjusts atom positions to minimise total energy
- **Convergence**: Maximum 1000 SCF iterations per geometry step, maximum 1000 geometry steps
- **Parallelism**: MPI with `--nslots` processes (`mpirun -np N nwchem input.nw`)

**How it works**:
1. For each geometry step, NWChem solves the Kohn-Sham equations self-consistently (the "SCF" loop you see in `output.nw`)
2. From the converged electron density, it computes forces on atoms
3. The `driver` module uses these forces to propose new atomic positions
4. Repeat until forces are below threshold (geometry converged)

**What to look for in `output.nw`**:
```
Step   0    ← Geometry optimisation step number
d= 0,ls=0.0,diis     1   -402.17...   ← SCF iteration within a step
...
Step       Energy      Delta E   Gmax     Grms     Xrms     Xmax   Walltime
  0   -402.4753   -0.0001  0.00025  0.00009  0.00037  0.00087   1795.2
```
- **Energy** should decrease over steps
- **Gmax / Grms** are gradient norms — they must drop below NWChem's threshold
- **Walltime** is cumulative seconds

**Output**: Optimised geometry stored internally in NWChem's `.db` file, used as the starting point for Step 4.

---

## Step 4 — COSMO Solvation Optimisation

**Code**: Same NWChem run (second `task` block in the config file)  
**Config**: `COSMO_BP86_TZVP.config` → `cosmo ... end` block + second `task dft optimize`

**What it does**: Re-optimises the geometry, this time surrounded by a perfect conductor (infinite dielectric constant). This is the COSMO (Conductor-like Screening Model) solvation model.

**COSMO settings** (from the config file):
- `iscren -1` — surrogate for infinite permittivity (ideal conductor)
- `lineq 1` — use iterative numerical solver for COSMO equations
- `ificos 0` — use octahedron as the initial tessellation polyhedron
- `minbem 3` — three tessellation refinement passes (controls surface mesh density)
- `do_gasphase false` — skip redundant gas-phase calculation
- `do_cosmo_ks true` — use the Klamt-Schüürmann (KS) COSMO model

**How it works**:
1. The molecular surface is tessellated into small segments (triangular mesh elements)
2. Each segment gets a "screening charge" that represents how a perfect conductor would respond to the molecule's electron density
3. The geometry is re-optimised with these screening charges included in the energy
4. This produces the **sigma surface**: a set of point charges on the molecular surface

**What to look for in `output.nw`**:
```
COSMO solvation phase
d= 0,ls=0.0,diis     1   -402.52...   ← SCF with COSMO (energy more negative than vacuum)
```

**Output**: 
- `<job_name>.cosmo.xyz` — coordinates and charges of all surface segments
- Surface area and segment area information in the main output

---

## Step 5 — Sigma Surface Extraction

**Code**: `spGenerator.py` → `getSigmaMatrix()` (line ~510) using data from `NWChem_Wrapper.py` → `readCOSMO()` + `readOutput()`

**What it does**: Reads the raw COSMO output from NWChem and assembles the sigma surface matrix.

**Extracted data**:
- **Segment coordinates** (x, y, z) — from `<name>.cosmo.xyz`
- **Segment charges** (e) — from `<name>.cosmo.xyz`
- **Segment areas** (Å²) — from `output.nw` (the `print cosmo_mol_surface` directive)
- **Total surface area** (Å²) — from `output.nw`
- **Atom assignments** — which atom each segment belongs to

**Processing**:
1. Charge densities are computed: σ = charge / area for each segment
2. Unit conversions: atomic units → e/Å²
3. A sanity check verifies that the sum of segment areas matches the reported total surface area
4. (Optional) If an averaging radius is specified, a distance-weighted averaging algorithm smooths the charge densities across neighbouring segments

**Output**: `sigmaSurface.csv` — a matrix where each row is a surface segment with columns: x, y, z, charge, area, charge density, atom index.

---

## Step 6 — Sigma Profile Computation

**Code**: `spGenerator.py` → `getSigmaProfile()` (using output from `getSigmaMatrix()`)

**What it does**: Converts the continuous sigma surface into a discrete sigma profile — a histogram of charge densities weighted by segment areas.

**Parameters** (set in `RunRepeats.py`):
- **Bin range**: σ ∈ [−0.250, +0.250] e/Å²
- **Bin width**: 0.001 e/Å²
- **Number of bins**: 501

**How it works**:
1. Each surface segment is assigned to the bin matching its charge density
2. The segment's area is added to that bin
3. The result is normalised by total surface area, giving p(σ) — the probability of finding a given charge density on the molecular surface

**Physical meaning**:
- Peaks near σ = 0 indicate non-polar regions (alkyl groups)
- Peaks at σ > 0 indicate negative surface charge (hydrogen-bond acceptors: O, N lone pairs)
- Peaks at σ < 0 indicate positive surface charge (hydrogen-bond donors: O-H, N-H)

**Output**: `sigmaProfile.csv` — two columns: σ (charge density bin centres) and p(σ) (area fraction).

---

## Output Files Summary

After a successful run, the job folder contains:

| File | Description |
|---|---|
| `initialGeometry.xyz` | Starting geometry (from RDKit or user-provided) |
| `input.nw` | NWChem input script (auto-generated) |
| `output.nw` | Full NWChem output log (SCF iterations, energies, convergence) |
| `outputSummary.nw` | Last optimisation step extracted from `output.nw` |
| `finalGeometry.xyz` | DFT-optimised geometry (from the COSMO phase) |
| `sigmaSurface.csv` | Raw sigma surface (segment coordinates, charges, areas) |
| `sigmaProfile.csv` | **Final sigma profile** (σ bins and p(σ) values) |
| `<name>.cosmo.xyz` | COSMO segment data (NWChem raw output) |
| `<name>.db` | NWChem runtime database |
| `<name>.movecs` | Molecular orbital vectors (NWChem) |

The `sigmaProfile.csv` is the key output used downstream for COSMO-SAC thermodynamic modelling or machine learning.

---

## Configuration Files

Configuration files live in `Python/lib/_config/` and control the NWChem calculation. The active config is set by the `nwchemConfig` variable in `RunRepeats.py` (line 44).

| Config File | Functional | Basis Set | Notes |
|---|---|---|---|
| `COSMO_BP86_TZVP.config` | BP86 | def2-TZVP | **Default** — matches VT-2005 standard |
| `COSMO_HF_SVP.config` | HF | def2-SVP | Hartree-Fock (no correlation) |
| `COSMO_BP86_631Gss.config` | BP86 | 6-31G** | Smaller basis set |
| `COSMO_BP86_STO2G.config` | BP86 | STO-2G | Minimal basis (fast, less accurate) |
| `COSMO_b3lyp_TZVP.config` | B3LYP | def2-TZVP | Hybrid functional |

Each config has `_noautoz` (Cartesian coordinates instead of internal) and `_Iodine` (extended basis for iodine) variants.

---

## Troubleshooting

### SCF convergence is slow (many iterations at one step)
- Normal for molecules with unusual electronic structure (zwitterions, radicals, transition metals)
- The `ls=0.5` line-search dampening in the output indicates NWChem is auto-applying convergence aids
- If it stalls completely, try `--noautoz True`

### Job appears stuck but output.nw is not growing
- Check `docker ps` — the container may have been killed
- Check `docker logs <name>` for Python tracebacks
- NWChem's output is buffered; large SCF steps can take minutes with no disk writes

### Geometry optimisation takes many steps (>20)
- Common for flexible molecules or poor initial geometries
- Use `--initialxyz` with a pre-optimised geometry to reduce steps
- Each step involves a full SCF convergence, so this multiplies the total time

### "Could not find identifier provided" error
- The CAS number or identifier was not found in PubChem or CIRpy
- Use `--idtype SMILES` with a known SMILES string instead
