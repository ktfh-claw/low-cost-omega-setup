# Isolated pytest environment for bridge component tests.
#
# Builds pytest + the exact pinned python client from singnet/das (e12573cc,
# 3rd_party_slots/python_client) installed from a local clone with its gRPC
# stub compiled, mirroring the bridge Dockerfile. Only write-bridge tests are
# run inside this image; host python environments stay clean. Resolve the
# digest first, e.g.:
#
#   docker pull python:3.12-slim
#   docker build --build-arg PYTHON_IMAGE_DIGEST=sha256:<digest> \
#       -t omega-write-bridge-tests tests/
#
# Run (read-only source mount; cache provider disabled):
#
#   docker run --rm -e PYTHONPATH=/work -v $PWD:/work:ro \
#       omega-write-bridge-tests -q -p no:cacheprovider tests/

ARG PYTHON_IMAGE_DIGEST
FROM python@${PYTHON_IMAGE_DIGEST}

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir pytest grpcio-tools==1.72.1 \
    && git clone --filter=blob:none --no-checkout https://github.com/singnet/das.git /src/das \
    && git -C /src/das checkout e12573cc3a588db699c75b58b1b9e45ebf6d8d4d \
    && git -C /src/das submodule update --init --depth 1 3rd_party_slots/python_client/proto \
    && mkdir -p /src/das/3rd_party_slots/python_client/hyperon_das/_grpc \
    && touch /src/das/3rd_party_slots/python_client/hyperon_das/_grpc/__init__.py \
    && /opt/venv/bin/python -m grpc_tools.protoc \
       --proto_path=/src/das/3rd_party_slots/python_client/proto \
       --python_out=/src/das/3rd_party_slots/python_client/hyperon_das/_grpc \
       --pyi_out=/src/das/3rd_party_slots/python_client/hyperon_das/_grpc \
       --grpc_python_out=/src/das/3rd_party_slots/python_client/hyperon_das/_grpc \
       /src/das/3rd_party_slots/python_client/proto/distributed_algorithm_node.proto \
       /src/das/3rd_party_slots/python_client/proto/common.proto \
    && sed -i \
       -e 's/^import distributed_algorithm_node_pb2/import hyperon_das._grpc.distributed_algorithm_node_pb2/' \
       -e 's/^import common_pb2/import hyperon_das._grpc.common_pb2/' \
       /src/das/3rd_party_slots/python_client/hyperon_das/_grpc/*_pb2*.py \
    && /opt/venv/bin/pip install --no-cache-dir /src/das/3rd_party_slots/python_client \
    && site_packages=$(/opt/venv/bin/python -c 'import site; print(site.getsitepackages()[0])') \
    && cp -a /src/das/3rd_party_slots/python_client/hyperon_das/_grpc "$site_packages/hyperon_das/" \
    && rm -rf /src/das /var/lib/apt/lists/*

WORKDIR /work
ENTRYPOINT ["/opt/venv/bin/python", "-m", "pytest"]
