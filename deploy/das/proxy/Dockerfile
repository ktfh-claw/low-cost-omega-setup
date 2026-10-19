ARG PYTHON_IMAGE_DIGEST
FROM python@${PYTHON_IMAGE_DIGEST} AS builder

RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && python -m venv /opt/venv

# Keep the wire client aligned with the DAS source used to design this lane.
# Its generated gRPC package is not committed, so build it from the pinned
# proto submodule before packaging the client.
RUN git clone --filter=blob:none --no-checkout https://github.com/singnet/das.git /src/das \
    && git -C /src/das checkout e12573cc3a588db699c75b58b1b9e45ebf6d8d4d \
    && git -C /src/das submodule update --init --depth 1 3rd_party_slots/python_client/proto \
    && /opt/venv/bin/pip install --no-cache-dir grpcio-tools==1.72.1 \
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
    && cp -a /src/das/3rd_party_slots/python_client/hyperon_das/_grpc "$site_packages/hyperon_das/"

FROM python@${PYTHON_IMAGE_DIGEST}
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY app.py das_client.py ./
USER 65532:65532
ENTRYPOINT ["python", "/app/app.py"]
