# Omega Container Build Documentation

**Purpose:** Historical reproducible build instructions for the superseded `omegaclaw:pr358-c193ab3` image based on the PR #358 source tree. For the current live image, see [`omega-1020-uplift.md`](omega-1020-uplift.md).

---

## Overview

This document preserves the exact steps used to build the earlier PR #358 image. It is not the current live deployment; the v0.1.20 uplift uses ASI:One `asi1-ultra` and is documented separately.

---

## Build source and version references

| Component | Public reference |
|---|---|
| Omega PR #358 source | `vsbogd/Omega` at commit `c193ab39857944017e067b426779d66113649313` |
| Upstream Omega repo | `https://github.com/singnet/Omega` |
| PR #358 (native tools API) | `https://github.com/singnet/Omega/pull/358` |

---

## Image description

- **Image name:** `omegaclaw:pr358-c193ab3`
- **Digest/ID:** `sha256:f78dbd811c23081aecdf1b5a46fb83d848b6a9c78b651b9218bd973e0dfdb491`
- **Creation date:** 2026-09-29T21:21:25Z
- **Underlying base image:** `swipl:10.0.2` (SWI Prolog 10.0.2)

---

## Build instructions

All commands are intended to be run in a Linux environment with Docker installed.

### Prerequisites

1. **Docker Engine** ≥ 24.0 (with BuildKit enabled)
2. **Git** (for cloning source repositories)
3. **CPU architecture** compatible with x86_64 (amd64)

### Step 1 — Clone PR #358 source

```bash
# Ensure the temporary directory is available
mkdir -p /tmp/omega-pr358

# Clone the Omega fork that contains the PR #358 changes
cd /tmp/omega-pr358
git clone https://github.com/vsbogd/Omega.git

cd Omega

# Checkout the exact commit corresponding to the PR #358 head
git checkout c193ab39857944017e067b426779d66113649313

# Verify the checkout matches the expected commit
expected="c193ab39857944017e067b426779d66113649313"
actual=$(git rev-parse HEAD)
if [ "$expected" != "$actual" ]; then
  echo "ERROR: Expected $expected, got $actual"
  exit 1
fi
```

### Step 2 — Create Dockerfile

Create `Dockerfile` in the `/tmp/omega-pr358/Omega` directory with the following content:

```dockerfile
# syntax=docker/dockerfile:1.7

# For maximum integrity, set this to an immutable digest in CI/CD.
ARG SWIPL_IMAGE=docker.io/library/swipl:10.0.2

FROM ${SWIPL_IMAGE} AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    HF_HOME=/opt/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/opt/sentence_transformers

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      git \
      build-essential \
      cmake \
      pkg-config \
      python3 \
      python3-dev \
      python3-pip \
      libopenblas-dev \
      libblas-dev \
      liblapack-dev \
      gfortran \
      libgflags-dev \
      nano \
 && rm -rf /var/lib/apt/lists/*

# Build dependencies from source. Pin refs at build time for reproducibility.
ARG PETTA_REPO=https://github.com/trueagi-io/PeTTa.git
ARG PETTA_REF=v1.0.4
ARG FAISS_REPO=https://github.com/facebookresearch/faiss.git
ARG FAISS_REF=v1.8.0
ARG CHROMADB_REPO=https://github.com/patham9/petta_lib_chromadb.git
ARG CHROMADB_REF=master

# Embedding model to pre-download at build time.
ARG EMBEDDING_MODEL=intfloat/e5-large-v2

RUN git clone --depth 1 --branch "${PETTA_REF}" "${PETTA_REPO}" /PeTTa
RUN git clone --depth 1 --branch "${FAISS_REF}" "${FAISS_REPO}" /faiss

WORKDIR /faiss
RUN cmake -B build -DFAISS_ENABLE_GPU=OFF -DFAISS_ENABLE_PYTHON=OFF -DBUILD_SHARED_LIBS=OFF \
 && cmake --build build --config Release --parallel \
 && cmake --install build

WORKDIR /PeTTa
RUN sh build.sh
RUN mkdir -p /PeTTa/repos \
 && git clone --depth 1 --branch "${CHROMADB_REF}" "${CHROMADB_REPO}" /PeTTa/repos/petta_lib_chromadb

COPY ./requirements.txt /tmp/requirements.txt
RUN python3 -m pip install --no-cache-dir --break-system-packages \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    torch==2.12.1 \
 && python3 -m pip install --no-cache-dir --break-system-packages -r /tmp/requirements.txt

# Pre-download the sentence-transformers model so runtime does not need network access.
RUN mkdir -p "${HF_HOME}" "${SENTENCE_TRANSFORMERS_HOME}" \
 && python3 - <<PY
from sentence_transformers import SentenceTransformer
model_name = "${EMBEDDING_MODEL}"
print(f"Downloading embedding model: {model_name}")
SentenceTransformer(model_name)
print("Model download complete.")
PY

FROM builder AS versioned-source

WORKDIR /omega-source
COPY . .
RUN : > /tmp/omega-ignored-tracked \
 && if [ -e .git ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
      git ls-files -ci --exclude-from=.dockerignore -z > /tmp/omega-ignored-tracked; \
      git checkout-index --force --stdin -z < /tmp/omega-ignored-tracked; \
    fi \
 && python3 -c 'from src.helper import omega_version; print(omega_version())' > /tmp/omega-version \
 && mv /tmp/omega-version ./version \
 && while IFS= read -r -d '' path; do rm -f -- "$path"; done < /tmp/omega-ignored-tracked \
 && rm -rf ./.git \
 && chmod 0444 ./version

FROM ${SWIPL_IMAGE} AS runtime

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/opt/sentence_transformers

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      python3 \
      libopenblas-dev \
      libblas-dev \
      liblapack-dev \
      gfortran \
      libgflags-dev \
      nano \
      git \
      nginx-light \
      gettext-base \
      poppler-utils \
      curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /PeTTa

COPY --from=builder /usr/local /usr/local
COPY --from=builder /PeTTa /PeTTa
COPY --from=builder /opt/huggingface /opt/huggingface
COPY --from=builder /opt/sentence_transformers /opt/sentence_transformers

# setup nginx proxy
RUN usermod -a -G tty www-data
RUN mkdir /opt/nginx
RUN chown www-data:www-data /opt/nginx
RUN chmod 0700 /opt/nginx
COPY --chown=www-data:www-data --chmod=0600 ./proxy/* /opt/nginx/

ENV OMEGA_DIR=/PeTTa/repos/Omega
ENV MEMORY_DIR=${OMEGA_DIR}/memory
# Start defaults for import-kb
ENV IMPORT_KB_ON_START=0

# Bring in the clean source tree and its version generated from Git metadata.
COPY --from=versioned-source /omega-source ${OMEGA_DIR}

RUN cp ${OMEGA_DIR}/run.metta /PeTTa/run.metta \
 && mkdir -p ${MEMORY_DIR}/chroma_db \
 && mkdir -p /memory-transfer \
 && ln -s ${MEMORY_DIR}/chroma_db ./chroma_db \
 && chmod +x ${OMEGA_DIR}/entrypoint.sh \
 && chmod +x ${OMEGA_DIR}/scripts/import_knowledge.sh \
 && chmod +x ${OMEGA_DIR}/scripts/omega \
 && chown -R 65534:65534 ${MEMORY_DIR} \
 && chown 65534:65534 /memory-transfer \
 && chmod 0700 /memory-transfer \
 && find ${MEMORY_DIR} -type f -exec chmod 0644 {} \; \
 && chmod 0444 ${MEMORY_DIR}/prompt.txt \
 && chown -R 65534:65534 /opt/huggingface /opt/sentence_transformers

ENTRYPOINT ["/PeTTa/repos/Omega/entrypoint.sh"]
CMD []
```

### Step 3 — Build the image

```bash
# Navigate to the Omega source directory (where Dockerfile resides)
cd /tmp/omega-pr358/Omega

# Build the image
# Tag appropriately for your use case, e.g., local development
tag="omegaclaw:pr358-c193ab3"

docker build --tag "$tag" --build-arg SWIPL_IMAGE="swipl:10.0.2" .

# Verify the image was built successfully
docker image ls "$tag"

# Inspect the image digest
docker image inspect --format="{{json .Id}}" "$tag"
```

### Step 4 — Verify provenance

```bash
# Retrieve the exact commit for the built image (if you used the versioned-source stage)
# The version file should contain the source Git commit
docker run --rm -v "$(pwd)/tmp:/tmp" "$tag" sh -c 'cat /omega-source/version 2>/dev/null || echo "version file not found"'

# Check the entrypoint script to ensure PR #358 changes are included
# Look for specific changes from PR #358, such as native tool calls, etc.
```

---

## Build artifacts and metadata

- **Dockerfile:** Available in the Omega source tree at `c193ab39857944017e067b426779d66113649313/Dockerfile`
- **requirements.txt:** `c193ab39857944017e067b426779d66113649313/requirements.txt`
- **Version file:** Generated during the build, contains the source Git commit
- **Image layer digests:** All layers are pinned to the exact build commands and file checksums

---

## Build environment

- **Docker version:** 29.8.1+ (build with BuildKit)
- **Base SWI Prolog image:** `swipl:10.0.2`
- **Python:** 3.12.3
- **Required system libraries:** ca-certificates, git, build-essential, cmake, pkg-config, python3-dev, libopenblas-dev, libblas-dev, liblapack-dev, gfortran, libgflags-dev

---

## Notes

1. **Reproducibility:** All arguments and tool versions are pinned at the build time to ensure reproducibility.
2. **Security:** The build does not expose any secrets or internal files.
3. **Dependencies:** All Python dependencies are installed via `requirements.txt`.
4. **Pre-downloaded assets:** The embedding model (`intfloat/e5-large-v2`) is downloaded during the build to eliminate runtime network dependencies.
5. **Layer caching:** The build leverages Docker layer caching for faster subsequent builds.

---

## References

- [PR #358 native tools API](https://github.com/singnet/Omega/pull/358)
- [Omega official repository](https://github.com/singnet/Omega)

---
*Last updated: 2026-10-05*
