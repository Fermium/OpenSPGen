# -*- coding: utf-8 -*-
"""
RDKit_Wrapper is a wrapper for RDKit. Its main purpose is to generate initial,
consistent conformers for molecules (consistency maintained using random seeds).
The main function of this module is generateConformer(), which generates a
conformer for a molecule using the MMFF force field implementation of RDKit.

Sections
    . Imports
    
    . Main Functions
        . generateConformer()
        . moleculeFromMol2()
    
    . Auxiliary Functions
        . getInitialConformer()
        . generateCustomMMFF()

Last edit: 2025-01-29
Author: Dinis Abranches, Fathya Salih
"""

# =============================================================================
# Imports
# =============================================================================

# General
import copy

# Specific
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem import rdForceFieldHelpers as rdff
from rdkit.Chem import Descriptors, rdMolDescriptors, rdFreeSASA
from rdkit.Chem.MolStandardize.rdMolStandardize import TautomerEnumerator

# =============================================================================
# Main Functions
# =============================================================================

def generateConformer(smilesString,xyzPath=None,calc_energy=False,
                      numConformers=3):
    """
    generateConformer() generates an initial, consistent conformer for the
    desired molecule. To do so, it relies on the MMFF force field
    implementation of RDKit (as described in 10.1186/s13321-014-0037-3).
    
    The algorithm was developed with two main objectives:
        1. To consistently return the same conformer for a given molecule;
        2. To minimize the energy of the conformer
    
    The algorithm is divided into three main steps:
        1. Generation of a random initial conformer using the distance geometry
        method implemented in RDKit;
        2. Minimization of the initial conformer with the default
        version of MMFF.
            
    The above steps are repeated *numConformers* times and the lowest energy
    conformation is kept. This redundancy fixes rare cases of bad convergence
    from the initial structure generated with the distance geometry method.
    
    Parameters
    ----------
    smilesString : string
        SMILES string of the molecule of interest.
    xyzPath : string, optional
        Path where the xyz file of the conformer should be saved. If none, 
        no xyz file is saved.
        The default is None.
    calc_energy : bool, optional
        If True, the function returns the energy and surface area of the
        conformer. If False, only the molecule object is returned.
    numConformers : int, optional
        Number of independent conformers to generate and minimise before
        selecting the lowest-energy one.  Default is 3 (original behaviour).

    Returns
    -------
    molecule : rdkit.Chem.rdchem.Mol object
        Molecule object of interest with the conformer embedded.

    """
    if not smilesString:
        raise ValueError("No SMILES string provided for conformer generation.")
    # Initiate list of energies and list of conformers
    energies=[]
    mList=[]
    for n in range(numConformers):
        # Build molecule object with initial 3D coordinates
        molecule=getInitialConformer(smilesString,randomSeed=n)
        # Skip procedure if number of atoms is inferior to 5
        if molecule.GetNumAtoms()<5:
            if xyzPath is not None: Chem.MolToXYZFile(molecule,xyzPath)
            return molecule
        # Generate standard MMFF
        prop,ff=generateCustomMMFF(molecule)    
        # Relax molecule under standard MMFF
        ff.Minimize(10**6)
        # Recenter molecule coordinates
        Chem.rdMolTransforms.CanonicalizeMol(molecule)
        # Append conformer to list of conformers
        mList.append(copy.deepcopy(molecule))
        # Evaluate energy of the conformer and append 
        energies.append(ff.CalcEnergy())
    # Retrieve conformer with the lowest energy
    molecule=mList[np.argmin(energies)]
    # Calculate SASA for selected molecule
    radii=rdFreeSASA.classifyAtoms(molecule)
    sasa=rdFreeSASA.CalcSASA(molecule, radii)
    # If an XYZ file is requested, save XYZ file
    if xyzPath is not None: Chem.MolToXYZFile(molecule,xyzPath)
    # Output
    if calc_energy:
        # return molecule,np.max(energies)
        return molecule,energies[np.argmin(energies)],sasa
    else:
        return molecule
   
def moleculeFromMol2(mol2Path, xyzPath=None):
    """
    moleculeFromMol2() generates a molecule object from a mol2 file.
    This allows pre-optimizing a provided geometry using a standard MMFF
    force field.

    Parameters
    ----------
    mol2Path : string
        Path to the mol2 file.
    xyzPath : string, optional
        Path where the xyz file of the conformer should be saved. If none, 
        no xyz file is saved.
        The default is None.

    Returns
    -------
    molecule : rdkit.Chem.rdchem.Mol object
        Molecule object of interest.

    """
    # Read mol2 file
    molecule=Chem.MolFromMol2File(mol2Path)
    # Add hydrogens to molecule object
    molecule=AllChem.AddHs(molecule)
    # Optimize molecule using standard MMFF
    AllChem.MMFFOptimizeMolecule(molecule)
    # If an XYZ file is requested, save XYZ file
    if xyzPath is not None: Chem.MolToXYZFile(molecule,xyzPath)
    # Output
    return molecule

# =============================================================================
# Auxiliary Functions
# =============================================================================

def getInitialConformer(smilesString,randomSeed=42,xyzPath=None):
    """
    !!! Generation seeded !!!
    
    Generate a molecule object from a SMILES string with an initial 3D
    conformer. The initial conformation is obtained using the default DG-based
    algorithm implemented in RDKit and is relaxed using the standard version
    of MMFF.

    Parameters
    ----------
    smilesString : string
        SMILES string of the molecule of interest.

    Returns
    -------
    molecule : rdkit.Chem.rdchem.Mol object
        Molecule object with an embedded initial conformer.

    """
    # Get molecule object from smiles string
    molecule=Chem.MolFromSmiles(smilesString)
    if molecule is None:
        raise ValueError(
            f"RDKit could not parse SMILES: '{smilesString}'. "
            "Please check the SMILES string and try again."
        )
    # Add hydrogens to molecule object
    molecule=AllChem.AddHs(molecule)
    # Generate initial 3D structure of the molecule
    status=AllChem.EmbedMolecule(molecule,randomSeed=randomSeed)
    if status==-1:
        # Distance-geometry failed — retry with random coordinates
        params=AllChem.ETKDGv3()
        params.randomSeed=randomSeed
        params.useRandomCoords=True
        status=AllChem.EmbedMolecule(molecule,params)
        if status==-1:
            raise RuntimeError(
                f"RDKit EmbedMolecule failed for SMILES '{smilesString}' "
                f"(seed={randomSeed}) even with useRandomCoords=True. "
                "The molecule may have a chemically unrealisable topology."
            )
    # Minimize initial guess with MMFF
    AllChem.MMFFOptimizeMolecule(molecule)
    # If an XYZ file is requested, save XYZ file
    if xyzPath is not None: Chem.MolToXYZFile(molecule,xyzPath)
    # Output
    return molecule

def generateCustomMMFF(molecule):
    """
    generateCustomFF() generates custom property and force field objects for
    the inputted molecule. In other words, it performs atom typing and assigns
    MMFF94s parameters to each degree of freedom
    (see 10.1186/s13321-014-0037-3).
    
    Parameters
    ----------
    molecule : rdkit.Chem.rdchem.Mol object
        Molecule object of interest. Must have already a conformer embedded.

    Returns
    -------
    prop : rdkit.ForceField.rdForceField.MMFFMolProperties
        MMFF molecule property object
    ff : rdkit.ForceField.rdForceField.ForceField object
        Force field object associated to molecule.

    """
    # Initiate props object (rdkit.ForceField.rdForceField.MMFFMolProperties)
    prop=rdff.MMFFGetMoleculeProperties(molecule,
                                                       mmffVariant='MMFF94s')
    ff=rdff.MMFFGetMoleculeForceField(molecule,prop)
    
    # Output
    return prop,ff


def enumerateTautomers(smilesString, maxTautomers=25):
    """
    Enumerate tautomers of a molecule using RDKit's TautomerEnumerator.

    Parameters
    ----------
    smilesString : str
        Canonical SMILES of the molecule.
    maxTautomers : int, optional
        Maximum number of tautomers to return.  Default is 25.

    Returns
    -------
    tautomers : list of str
        List of unique canonical SMILES for each tautomer found
        (always includes the input molecule).
    """
    mol = Chem.MolFromSmiles(smilesString)
    if mol is None:
        raise ValueError(f"RDKit could not parse SMILES: '{smilesString}'.")

    enumerator = TautomerEnumerator()
    enumerator.SetMaxTautomers(maxTautomers)

    tauts = enumerator.Enumerate(mol)
    seen = set()
    results = []
    for t in tauts:
        smi = Chem.MolToSmiles(t)
        if smi not in seen:
            seen.add(smi)
            results.append(smi)
    return results


def tautomerProperties(smilesList):
    """
    Compute quick physicochemical descriptors for a list of tautomer SMILES.

    For each tautomer the function returns:
    - Relative MMFF94s energy (kcal mol⁻¹, lowest = 0)
    - Number of H-bond donors  (Lipinski definition)
    - Number of H-bond acceptors (Lipinski definition)
    - Topological Polar Surface Area (Å²)

    Parameters
    ----------
    smilesList : list of str
        Canonical SMILES strings for each tautomer.

    Returns
    -------
    props : list of dict
        One dict per SMILES with keys: 'smiles', 'rel_energy', 'hbd', 'hba',
        'tpsa'.  If a conformer cannot be generated for a tautomer, 'rel_energy'
        will be None.
    """
    energies = []
    props = []
    for smi in smilesList:
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            props.append({'smiles': smi, 'rel_energy': None,
                          'hbd': None, 'hba': None, 'tpsa': None})
            energies.append(None)
            continue

        hbd = Descriptors.NumHDonors(mol)
        hba = Descriptors.NumHAcceptors(mol)
        tpsa = rdMolDescriptors.CalcTPSA(mol)

        # Quick single-conformer MMFF energy
        energy = None
        try:
            mol3d = Chem.AddHs(mol)
            AllChem.EmbedMolecule(mol3d, randomSeed=42)
            if mol3d.GetNumConformers() > 0:
                mp = AllChem.MMFFGetMoleculeProperties(mol3d, 'MMFF94s')
                if mp is not None:
                    ff = AllChem.MMFFGetMoleculeForceField(mol3d, mp)
                    if ff is not None:
                        ff.Minimize(5000)
                        energy = ff.CalcEnergy()
        except Exception:
            pass

        energies.append(energy)
        props.append({'smiles': smi, 'rel_energy': energy,
                      'hbd': hbd, 'hba': hba, 'tpsa': tpsa})

    # Convert absolute energies to relative (lowest = 0)
    valid = [e for e in energies if e is not None]
    if valid:
        emin = min(valid)
        for p in props:
            if p['rel_energy'] is not None:
                p['rel_energy'] = round(p['rel_energy'] - emin, 2)

    return props


def detectZwitterion(smilesString):
    """
    Heuristic check for zwitterionic character in a SMILES string.

    Returns True if the molecule contains at least one atom with a positive
    formal charge and at least one with a negative formal charge while the
    overall net charge is zero.
    """
    mol = Chem.MolFromSmiles(smilesString)
    if mol is None:
        return False
    has_pos = any(a.GetFormalCharge() > 0 for a in mol.GetAtoms())
    has_neg = any(a.GetFormalCharge() < 0 for a in mol.GetAtoms())
    net = sum(a.GetFormalCharge() for a in mol.GetAtoms())
    return has_pos and has_neg and net == 0
