# OpenSPGen
An open source sigma profile generator.

![plot](./imgs/workflow.png)

The journal article associated with this work is available on DigitalDiscovery:[Open-source generation of sigma profiles: impact of quantum chemistry and solvation treatment on machine learning performance](https://pubs.rsc.org/en/content/articlelanding/2025/dd/d5dd00087d). Along with an earlier pre-print on [ChemRxiv](https://chemrxiv.org/engage/chemrxiv/article-details/67bc9bf6fa469535b9bb872e).

## Installation Instructions 

### With Existing/Separate NWChem Installation

These instructions are for the case where the user has an existing NWChem installation (has to be at least version `7.2.0` or higher) or a the user would like to install NWChem with specific build instructions (the basic build is sufficient for this package).

1. Install the open source DFT package `NWChem` without Python support (note the compatible versions listed below).
21. Add the path of the `nwchem` executable to your `PATH` variable (the `nwchem` executable path should be along the lines of: `User/Desktop/nwchem-7.2.0-beta2/bin/LINUX64`)
1. Download the current repository to your local machine.
1. Add the path of the main python script (`<OpenSPGen-installation-path>/Python`) to your `PATH` variable.
1. Create a conda environment where you can install `rdkit` and its dependencies from the provided `yml` file using the following instructions:
   ```
   # Go to the directory where the repository was installed
   cd <OpenSPGen-installation-path>
   cd Python
   # Create a conda environment for all the dependencies
   conda env create -n spg-env --file spg.yml
   ```
1. Run the installation tests (will run a sigma profile generation job for methane with different inputs - a SMILES, a CAS number and a pre-optimized xyz). *You may need to edit the environment section of the script before running tests.*
   ```
   ./run-tests.sh
   ```

**Notes on Compatibility**: 
- Because the DFT software used in this package is only available for Linux and macOS distributions, the complete tool can only be run and should be installed on those machines. 

- The version of NWChem used during the development of this package is `7.2.0-beta2` available for download [here](https://github.com/nwchemgit/nwchem/releases/tag/v7.2.0-beta2)*. Functionality has been tested with later versions (versions `7.2.*` and `7.3.0` to be specific), but consistency of the produced sigma profiles with version `7.2.0-beta2` has not been tested and is not expected.

### Through `conda` (Preferred)

These instructions are for a user who would like all functionalities to be present within the same conda environment. Here, NWChem along with the necessary python dependencies are installed through conda from an environment file using the following instructions:

   ```
   # Go to the directory where the repository was installed
   cd <OpenSPGen-installation-path>
   cd Python
   # Create a conda environment for all the dependencies
   conda env create -n spg-env --file spg-7.3.yml
   ```
Then, you can run the installation tests (will run a sigma profile generation job for methane with different inputs - a SMILES, a CAS number and a pre-optimized xyz). *You may need to edit the environment section of the script before running tests.*
   ```
   ./run-tests.sh
   ```

**Note**: This will install NWChem v 7.3.0, as well as more recent versions of RDKit and Python. As such, the software installed by these 2 methods should complete jobs successfully, but should not be expected to produce the same sigma profiles.

### Through Docker (Recommended for macOS / ARM)

Docker provides a fully self-contained environment with NWChem, RDKit, and all dependencies pre-configured. This is the simplest option, especially on Apple Silicon (ARM) Macs where building NWChem natively can be difficult.

**Prerequisites**: [Docker Desktop](https://www.docker.com/products/docker-desktop/) or [OrbStack](https://orbstack.dev/) must be installed and running.

1. Build the Docker image from the repository root:
   ```bash
   cd <OpenSPGen-installation-path>
   docker build -t openspgen-arm .
   ```

2. Run the installation tests:
   ```bash
   docker run --rm -v "$(pwd):/app" -w /app openspgen-arm ./run-tests.sh
   ```

#### Running a Job with Docker

Use `docker run -d` (detached mode) so the job survives terminal closures and interruptions:

```bash
cd <OpenSPGen-installation-path>

# Basic example: generate sigma profile for methane
docker run -d --name methane_job \
  -v "$(pwd):/app" -w /app openspgen-arm \
  /bin/bash -c "python Python/RunRepeats.py --idtype SMILES --id C --charge 0 --nslots 4 --name Methane"
```

With a pre-existing initial geometry (skips PubChem lookup and MMFF pre-optimization):

```bash
docker run -d --name betaine_job \
  -v "$(pwd):/app" -w /app openspgen-arm \
  /bin/bash -c "python Python/RunRepeats.py \
    --idtype CAS-Number --id 107-43-7 --charge 0 \
    --name Betaine --initialxyz /app/path/to/geometry.xyz --nslots 8"
```

**Important notes on Docker usage**:
- Always use `-d` (detached mode). Without it, closing the terminal or pressing Ctrl+C will kill the NWChem computation.
- Use `--name <job_name>` to give the container a recognisable name.
- The `-v "$(pwd):/app"` flag mounts the current directory into the container, so output files appear directly on your host filesystem.
- When using `--initialxyz`, provide the **absolute path inside the container** (starting with `/app/`).

#### Checking Job Progress

```bash
# Is the container still running?
docker ps

# View Python/NWChem stdout (errors, config messages)
docker logs <container_name>

# Check which geometry optimisation step NWChem is on
grep "Step " SP-<job_folder>/<job_subfolder>/output.nw | tail -5

# View the latest SCF iterations
tail -10 SP-<job_folder>/<job_subfolder>/output.nw

# Check if the sigma profile CSV has been generated (= job complete)
find SP-<job_folder> -name "sigmaProfile.csv"
```

#### Running Multiple Jobs in Parallel

Launch each molecule in its own detached container:

```bash
docker run -d --name job_water \
  -v "$(pwd):/app" -w /app openspgen-arm \
  /bin/bash -c "python Python/RunRepeats.py --idtype CAS-Number --id 7732-18-5 --charge 0 --name Water --nslots 4"

docker run -d --name job_glycol \
  -v "$(pwd):/app" -w /app openspgen-arm \
  /bin/bash -c "python Python/RunRepeats.py --idtype CAS-Number --id 57-55-6 --charge 0 --name Glycol --nslots 4"
```

Note that parallel jobs share CPU resources. For heavy molecules, running sequentially with full core allocation (`--nslots 8`) is often faster than running in parallel with split cores.

#### Cleanup

```bash
# Stop a running job
docker stop <container_name>

# Remove a stopped container
docker rm <container_name>

# Remove all stopped containers
docker container prune
```

## Usage Instructions

**Simple usage example**:

   ```
   # From the directory you wish your jobs to be saved at
   conda activate spg-env
   python <OpenSPGen-installation-path>/Python/RunRepeats.py --idtype SMILES --id C --charge 0 --nslots 4 --name Methane
   ```

More examples using different molecular identifiers are provided in `run-sp-job.sh` and `run-tests.sh`.

The below help message summarizes the required and optional user arguments. And it can be generated by running `python <OpenSPGen-installation-path>/Python/RunRepeats.py --help`.

```
usage: RunRepeats.py [-h] --idtype IDTYPE --id ID [--charge CHARGE] [--initialxyz INITIALXYZ] [--preoptimize PREOPTIMIZE] [--name NAME] [--nslots NSLOTS] [--njobs NJOBS] [--noautoz NOAUTOZ]
                     [--iodine IODINE]

options:
  -h, --help            show this help message and exit
  --idtype IDTYPE       Molecule identifier type. Options: SMILES, CAS-Number, InChI, InChIKey, or mol2 (Not case sensitive, but must include separators like `-`). This argument is required.
  --id ID               Molecule identifier. This argument is required.
  --charge CHARGE       Molecule charge. Default is None and will be calculated later on using `rdkit.Chem.rdmolops`.
  --initialxyz INITIALXYZ
                        Path to initial xyz file for NWChem geometry optimization, if desired. Otherwise, use 'Random' or 'None' for a random conformer.
  --preoptimize PREOPTIMIZE
                        Pre-optimize the molecule using a standard forcefield (MMFF94). Options: True or False. Only available if a `mol2` idtype is provided.
  --name NAME           Tail for the job name. Default is `UNK`.
  --nslots NSLOTS       Number of cores/threads to use for NWChem calculations. Default is 4.
  --njobs NJOBS         Number of repeat jobs to be run. Default is 1.
  --noautoz NOAUTOZ     NWChem setting to disable use of internal coordinates. Default is False.
  --iodine IODINE       The molecule contains an iodine atom. Default is False.
```

### Additional Usage Notes

- It is not recommended to generate SPs for large molecules or structures with large cycles without a starting initial geometry. All identifier types other than an initial xyz or `mol2` require generating an initial structure from a SMILES string retrieved from PubChem, and the `rdkit.Chem.rdmolfiles.MolFromSmiles()` function is likely to have trouble generating structures with nested cycles (e.g. cucurbiturils or cyclodextrins).


## Available Data
This repository is associated with a study on the effect of quantum chemistry on the performance of machine learning models to predict thermophysical properties from sigma profiles. The datasets discussed in that work are available in this repository in the `manuscript-databases` folder. These include:

- **Sigma profile databases**: `csv` files including sigma profile databases for 1432 molecules under different levels of theory. The naming indicates the basis set and functional used to generate that dataset (e.g. `sp_functional_basis-set.csv`). 
   - All the sigma profiles in those datasets are unaveraged, except for `sp_mullins_vt-2005.csv`, which contains the sigma profiles published by Mullins (2006)**. These are equivalent to applying the averaging radius of 0.8174 to the unaveraged Mullins dataset `sp_mullins_no_av`.
- **Input geometries**: Starting geometries used in the quantum chemistry studies are in the folder: `manuscript-databases/VT-2005_XYZs`.
- **GP training results**: the folder `manuscript-databases/GP-Training-HF_yk` contains the target property datasets along with GP models pre-trained on the sigma profile dataset with the recommended combination of level of theory and COSMO model (HF/SVP with the YK*** COSMO model). The folder contains:
   - `gpflow-env.yml`: environment file for the packages used to train GP models on already generated sigma profiles.
   - `k-fold-Target-Databases`: thermophysical property databases split into 10 stratified training and testing folds. The datasets labeled `_Original` contain the complete dataset of thermophysical properties.
   - `optimized_models`: GP models pre-trained on the mentioned dataset. Models are labeled a target property code and a k-fold number (e.g. `BP_model_1.pkl` predicts boiling point and was trained on fold #1).
   - `parity_plots`: parity plots for the performance of different trained models.
   - `performance_per_fold`: `csv` files for the performance of different trained models.
   - *Averaged Performances*: `avg_mae.csv`, `avg_R2.csv`, `std_mae.csv`, `std_R2.csv` are the GP performances averaged over the different training folds.
- **Example Usage of Pre-trained GP Model**: the notebook `manuscript-databases/deploy_gp_model.ipynb` shows how to use one of the pre-trained GP models to predict a thermophysical property for a given sigma profile. 
- **Example For Training a GP Model**: the notebook `manuscript-databases/GP-Training-HF_yk/train-gp-model.ipynb` shows how to train a GP model to predict a thermophysical property for a given SP dataset and a specified data split (or k-fold). The script `manuscript-databases/GP-Training-HF_yk/train-gp-model.py` shows the same training example but for multiple target properties and multiple SP datasets for a given k-fold. This is accompanied by a short bash script (`manuscript-databases/GP-Training-HF_yk/train-gp-model.sh`) that shows how it is used to generate the averaged performance results shown in the manuscript.

## References
** Mullins, E.; Oldland, R.; Liu, Y. A.; Wang, S.; Sandler, S. I.; Chen, C.-C.; Zwolak, M.; Seavey, K. C. Sigma-Profile Database for using COSMO-Based thermodynamic methods. *Industrial & Engineering Chemistry Research* **2006**, 45 (12), 4389–4415. https://doi.org/10.1021/ie060370h.

*** York, D. M.; Karplus, M. A Smooth Solvation Potential Based on the Conductor-Like Screening Model. *The Journal of Physical Chemistry A* **1999**, 103 (50), 11060–11079. https://doi.org/10.1021/jp992097l.
