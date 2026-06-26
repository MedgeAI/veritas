# ELIS Forensic Provenance — HTTP Service
#
# Extends the existing veritas-elis-provenance:latest image (Miniconda +
# cyvlfeat + provenance analysis code) with a FastAPI HTTP wrapper so the
# provenance engine stays warm across requests.
#
# The wrapper bypasses CBIR and calls provenance analysis directly —
# the same code path as the CLI `provenance` subcommand.
#
# Build:  docker build -t veritas-elis-forensic-service:latest deploy/forensics/elis-forensic/
# Run:    docker run -p 8771:8771 -v /path/to/project:/data veritas-elis-forensic-service

FROM veritas-elis-provenance:latest

LABEL maintainer="Veritas"
LABEL description="ELIS forensic provenance analysis HTTP service"

# Install uvicorn inside the conda environment.
# FastAPI is already in requirements.txt of the base image.
SHELL ["conda", "run", "-n", "provenance", "/bin/bash", "-c"]
RUN pip install --no-cache-dir "uvicorn[standard]"

# Copy the service wrapper.
WORKDIR /app
COPY api_wrapper.py /app/api_wrapper.py
COPY entrypoint.sh /app/entrypoint.sh

# Reset shell to default (conda env is activated by entrypoint).
SHELL ["/bin/bash", "-c"]

RUN chmod +x /app/entrypoint.sh

# curl for HEALTHCHECK.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

EXPOSE 8771

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8771/health || exit 1

# Run inside the conda environment.
ENTRYPOINT ["conda", "run", "--no-capture-output", "-n", "provenance", "/app/entrypoint.sh"]
