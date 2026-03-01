FROM continuumio/miniconda3

WORKDIR /app

# Copy the repository content
COPY . /app

# Create the conda environment
RUN conda env create -f Python/spg-arm64.yml

# Set path to use the environment by default
ENV PATH /opt/conda/envs/spg-7.3/bin:$PATH
ENV PATH /app/Python:$PATH

# Fix run-tests.sh
# 1. Remove module load/purge
# 2. Remove conda activate/deactivate (since we are setting PATH and the env name might differ)
# 3. Ensure NSLOTS is set
RUN sed -i 's/module load.*//g' run-tests.sh && \
    sed -i 's/module purge//g' run-tests.sh && \
    sed -i 's/conda deactivate//g' run-tests.sh && \
    sed -i 's/conda activate.*//g' run-tests.sh

# Set NSLOTS env var default
ENV NSLOTS=1

# Allow running as root for OpenMPI
ENV OMPI_ALLOW_RUN_AS_ROOT=1
ENV OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1

# Make scripts executable
RUN chmod +x run-tests.sh sub-tests.sh run-sp-job.sh

# Create .nwchemrc file
RUN echo "nwchem_basis_library /opt/conda/envs/spg-7.3/share/nwchem/libraries/" > /root/.nwchemrc && \
    echo "nwchem_nwpw_library /opt/conda/envs/spg-7.3/share/nwchem/libraryps/" >> /root/.nwchemrc && \
    echo "ff_amber_library /opt/conda/envs/spg-7.3/share/nwchem/amber_s/" >> /root/.nwchemrc && \
    echo "ff_spce_library /opt/conda/envs/spg-7.3/share/nwchem/solvents/" >> /root/.nwchemrc && \
    echo "ff_charmm_source /opt/conda/envs/spg-7.3/share/nwchem/charmm_s/" >> /root/.nwchemrc && \
    echo "ff_charmm_param /opt/conda/envs/spg-7.3/share/nwchem/charmm_p/" >> /root/.nwchemrc

# Default command
CMD ["./run-tests.sh"]
