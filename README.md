# OpenSPGen-App

[![Build & Push Images](https://github.com/Fermium/OpenSPGen/actions/workflows/docker-publish.yml/badge.svg)](https://github.com/Fermium/OpenSPGen/actions/workflows/docker-publish.yml)

A **Streamlit web UI** for [OpenSPGen](https://github.com/FaSalih/OpenSPGen) — the open-source sigma-profile generator.

Wraps [NWChem](https://nwchemgit.github.io/) (DFT + COSMO) and [RDKit](https://www.rdkit.org/) to produce COSMO sigma profiles from a molecule identifier (SMILES, CAS number, InChI, …). The browser-based interface provides live SCF convergence charts, 3-D molecular viewing, and one-click ZIP download of all results.

Based on the work published in Digital Discovery: [Open-source generation of sigma profiles: impact of quantum chemistry and solvation treatment on machine learning performance](https://pubs.rsc.org/en/content/articlelanding/2025/dd/d5dd00087d).

---

## Quick start

### Using pre-built images (recommended)

Pre-built images are published to the GitHub Container Registry on every push to `main`.

```bash
# Pull the images
docker pull ghcr.io/fermium/openspgen-nwchem:latest
docker pull ghcr.io/fermium/openspgen-app:latest

# Run
docker run -d --name openspgen-app \
  -p 8501:8501 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v openspgen-jobs:/app/jobs \
  -e OPENSPGEN_NWCHEM_IMAGE=ghcr.io/fermium/openspgen-nwchem:latest \
  ghcr.io/fermium/openspgen-app:latest
```

Then open **<http://localhost:8501>**.

> **macOS / OrbStack users**: replace `/var/run/docker.sock` with `~/.orbstack/run/docker.sock`.

### Building locally

```bash
# 1. Base NWChem image
docker build -t openspgen-nwchem .

# 2. Streamlit image
docker build -t openspgen-app -f streamlit_app/Dockerfile .

# 3. Run
docker run -d --name openspgen-app \
  -p 8501:8501 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v openspgen-jobs:/app/jobs \
  openspgen-app
```

---

## How it works

| Layer | Role |
|---|---|
| **App container** (`openspgen-app`) | Serves the Streamlit web UI, manages job state, launches NWChem jobs via the Docker socket |
| **NWChem container** (`openspgen-nwchem`) | Runs the DFT + COSMO computation as a sibling container |
| **Shared volume** (`openspgen-jobs`) | Mounted at `/app/jobs` in both containers so input/output files are accessible to both |

The pipeline steps are:

1. **Resolve** — look up the molecule (CAS → SMILES via PubChem / CIRpy)
2. **Conformer** — generate a 3-D starting geometry with RDKit MMFF94
3. **NWChem** — run BP86/def2-TZVP + COSMO (geometry optimisation + single-point)
4. **Parse** — extract COSMO surface charges and final geometry
5. **Sigma profile** — compute the σ-profile from the COSMO output

---

## Repository layout

```
.
├── Dockerfile                 # Base image (miniconda + NWChem + RDKit)
├── Python/
│   ├── lib/                   # Core OpenSPGen library
│   ├── spg-7.3.yml            # Conda env (x86_64)
│   └── spg-arm64.yml          # Conda env (ARM / Apple Silicon)
├── streamlit_app/
│   ├── Dockerfile             # Streamlit image (extends base)
│   ├── app.py                 # Main Streamlit UI
│   ├── pipeline.py            # 5-step orchestration
│   ├── docker_runner.py       # Docker SDK wrapper for NWChem
│   ├── job_state.py           # Job state management
│   ├── requirements.txt
│   └── components/            # UI components (viewers, charts, input)
└── README.md
```

---

## Configuration

The default NWChem settings are **BP86 / def2-TZVP** with the **COSMO** solvation model, defined in a config file written at job submission time. You can change the level of theory by editing `Python/lib/NWChem_Wrapper.py` or providing your own config.

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `OPENSPGEN_NWCHEM_IMAGE` | `openspgen-nwchem` | Docker image used to run NWChem jobs |
| `OPENSPGEN_JOBS_VOLUME` | *(auto-detected)* | Named volume shared between app and NWChem containers |
| `DOCKER_HOST` | `/var/run/docker.sock` | Docker socket path |

---

## Credits

This app is built on top of the [OpenSPGen](https://github.com/FaSalih/OpenSPGen) library.

## License

See [LICENSE](LICENSE).
