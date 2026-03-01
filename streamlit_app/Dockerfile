# ============================================================
# OpenSPGen-App  —  Streamlit web UI
# ============================================================
# Extends the base NWChem image (which provides the full conda
# env with RDKit, numpy, cirpy, pubchempy) and adds Streamlit +
# the Docker SDK.
#
# NWChem runs in a SEPARATE sibling container, dispatched via
# the Docker socket which is bind-mounted in.
#
# Build (from repo root):
#   docker build -t openspgen-app -f streamlit_app/Dockerfile .
#
# Run:
#   docker run -p 8501:8501 \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     -v openspgen-jobs:/app/jobs \
#     openspgen-app
#
# Then open http://localhost:8501
# ============================================================

ARG BASE_IMAGE=openspgen-nwchem
FROM ${BASE_IMAGE}

# Refresh code
COPY . /app

# Install Streamlit + visualisation + Docker SDK
RUN pip install --no-cache-dir \
    streamlit>=1.32 \
    plotly>=5.18 \
    docker>=7.0 \
    py3Dmol>=2.0 \
    stmol>=0.0.9

# Shared jobs directory — mount a named volume here so the NWChem
# sibling container (which also mounts it at /app/jobs) can read/write
# the same files.
RUN mkdir -p /app/jobs

EXPOSE 8501

WORKDIR /app

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "streamlit_app/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
