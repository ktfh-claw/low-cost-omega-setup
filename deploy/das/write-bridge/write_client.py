"""Narrow, security-bounded write adapter for the DAS atomdb-broker.

``DasWriteRunner`` writes MeTTa facts to the live DAS through the pinned
upstream python client (singnet/das e12573cc, 3rd_party_slots/python_client)
and verifies every write by structural read-back through the query engine.

Deployment invariants honored here (live-discovered 2026-10-18, see
docs/architecture.md section 5):

(a) the atomdb-broker binds 0.0.0.0 in multi-network docker;
(b) write clients MUST join the broker DIRECTLY -- this runner owns two
    separate service buses, one whose ONLY routable command is ``atomdb``
    (known_peer = broker endpoint) and one whose ONLY routable command is
    ``pattern_matching_query`` (known_peer = query engine). A mis-routed
    ATOMDB command crashes the query engine (upstream defect), so the
    command sets are structurally disjoint;
(c) the client-side callback-peer rewrite host is the BROKER DNS name for
    atomdb commands and the query-engine DNS name for pattern queries.

``AtomDBProxy.add_atoms`` is FIRE-AND-FORGET: the returned handles are
client-side constructions, not server acknowledgements. Read-back
verification (mandatory, never skipped silently) is therefore built in: each
written Expression link is queried with a fully ground LINK_TEMPLATE and the
answer handles are compared against the expected (deterministic) handles.
Node handles are verified transitively: every node in a parsed fact is a
target of at least one written link, and a link template only matches when
its target handles match.
"""

from __future__ import annotations

import math
import os
import re
import threading
import time
from typing import Any

from hyperon_das.query_answer import QueryAnswer
from hyperon_das.service_bus.proxy import DistributedAlgorithmNodeManager
from hyperon_das.service_bus.service_bus import ServiceBus
from hyperon_das.service_clients import AtomDBProxy, PatternMatchingQueryProxy

from metta_to_atoms import ParsedFact, UNASSIGNED_HANDLE, parse_fact

ATOMDB_COMMAND = "atomdb"
PATTERN_MATCHING_QUERY_COMMAND = "pattern_matching_query"

# Mirror of the C++ client's delete chunking (AtomDBProxy::COMMAND_SIZE_LIMIT).
DELETE_CHUNK_SIZE = 50

_MAX_WIRE_ANSWER_BYTES = 256 * 1024
_MAX_HANDLE_VECTORS = 64
_MAX_WIRE_HANDLES = 4096
_MAX_WIRE_ASSIGNMENTS = 64

_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Rewritten wildcard callback hosts, per bus command (refreshed on every
# runner construction; the patch itself is installed once).
_REWRITE_HOSTS: dict[str, str] = {}


class WriteFailure(RuntimeError):
    """A bridge operation failed; ``handles`` carries deterministic handles."""

    def __init__(self, message: str, handles: list[str] | None = None) -> None:
        super().__init__(message)
        self.handles = list(handles or [])


class DasWriteRunner:
    """Write one MeTTa fact at a time; verify it by structural read-back."""

    def __init__(
        self,
        *,
        atom_bus: Any = None,
        query_bus: Any = None,
    ) -> None:
        client_endpoint = os.environ["DAS_CLIENT_ENDPOINT"]
        broker_endpoint = os.environ["DAS_BROKER_ENDPOINT"]
        broker_peer_host = os.environ["DAS_BROKER_PEER_HOST"]
        query_engine = os.environ["DAS_QUERY_ENGINE"]
        port_lower = int(os.environ["DAS_CALLBACK_PORT_LOWER"])
        port_upper = int(os.environ["DAS_CALLBACK_PORT_UPPER"])
        self.verify_timeout = float(os.getenv("DAS_VERIFY_TIMEOUT_SECONDS", "30"))
        self.peer_join_timeout = float(os.getenv("DAS_PEER_JOIN_TIMEOUT_SECONDS", "10"))

        query_engine_host = _hostname_of(query_engine, "DAS_QUERY_ENGINE")
        _validate_hostname(broker_peer_host, "DAS_BROKER_PEER_HOST")

        _install_nested_handle_decoder()
        _install_callback_peer_rewrite(
            {
                ATOMDB_COMMAND: broker_peer_host,
                PATTERN_MATCHING_QUERY_COMMAND: query_engine_host,
            }
        )

        # Invariant (b): each bus can route exactly one command, to exactly
        # one directly-joined peer. An atomdb command can never reach the
        # query engine and a pattern query can never reach the broker.
        self._atom_bus = atom_bus or ServiceBus(
            host_id=client_endpoint,
            known_peer=broker_endpoint,
            commands=[ATOMDB_COMMAND],
            port_lower=port_lower,
            port_upper=port_upper,
        )
        self._query_bus = query_bus or ServiceBus(
            host_id=client_endpoint,
            known_peer=query_engine,
            commands=[PATTERN_MATCHING_QUERY_COMMAND],
            port_lower=port_lower,
            port_upper=port_upper,
        )
        self._atom_lock = threading.Lock()
        self._query_lock = threading.Lock()

    # ------------------------------------------------------------------ write

    def write(self, metta: str, verify: bool = True) -> dict[str, Any]:
        """Parse, write and (by default) verify one MeTTa fact.

        Returns ``{"written": [handles], "verified": bool | None,
        "missing": [handles]}``. ``verified`` is ``None`` when verification
        was skipped; ``missing`` only ever contains link handles (nodes are
        verified transitively through the links that reference them).
        """
        fact = parse_fact(metta)
        try:
            self.add_atoms(fact.atoms)
        except Exception as exc:
            raise WriteFailure(f"atomdb write failed: {exc}", fact.handles) from exc
        if not verify:
            return {"written": fact.handles, "verified": None, "missing": []}
        try:
            missing = self.verify_handles(fact)
        except Exception as exc:
            raise WriteFailure(f"read-back verification failed: {exc}", fact.handles) from exc
        return {
            "written": fact.handles,
            "verified": not missing,
            "missing": missing,
        }

    def add_atoms(self, atoms: list[Any]) -> list[str]:
        """Send atoms via the pinned ``AtomDBProxy`` (fire-and-forget).

        The proxy's built-in ``COMMAND_SIZE_LIMIT`` chunking is honored
        upstream of this method; no streaming.
        """
        proxy = AtomDBProxy()
        with self._atom_lock:
            self._issue_atomdb(proxy)
            try:
                return proxy.add_atoms(atoms, use_streaming=False)
            finally:
                _graceful_shutdown(proxy)

    def delete_atoms(self, handles: list[str], delete_link_targets: bool = False) -> None:
        """Delete atoms by handle via the broker (fire-and-forget, no ack).

        The pinned python client has no ``delete_atoms``; this follows the
        add_atoms wire pattern and the C++ client's delete format
        (AtomDBProxy.cc: chunked handle lists with a trailing
        delete_link_targets flag "1"/"0").
        """
        handles = list(handles)
        for handle in handles:
            if not isinstance(handle, str) or not _HANDLE_PATTERN.match(handle):
                raise ValueError(f"invalid atom handle: {handle!r}")
        if not handles:
            return
        proxy = AtomDBProxy()
        with self._atom_lock:
            self._issue_atomdb(proxy)
            try:
                flag = "1" if delete_link_targets else "0"
                for start in range(0, len(handles), DELETE_CHUNK_SIZE):
                    chunk = handles[start : start + DELETE_CHUNK_SIZE]
                    proxy.to_remote_peer("delete_atoms", [*chunk, flag])
            finally:
                _graceful_shutdown(proxy)

    # ----------------------------------------------------------------- verify

    def verify_handles(self, fact: ParsedFact) -> list[str]:
        """Variable-form query for every written link; return missing handles.

        The pinned engine never completes variable-free patterns (it answers
        an error string and the query hangs -- live-verified 2026-10-19,
        bridge iteration 2), so verification cannot use fully-ground
        templates. Each link is instead queried with its leading symbol
        bound to $unassigned (the completing form, live-proven in re-eval E1
        and this iteration's probe): the returned assignment binds the
        variable to the leading symbol's actual handle, which is compared
        against the expected assignment. All other positions stay fully
        ground, so a match still pins down the exact content. Nodes are
        verified transitively (every node is a target of some written link,
        and a template only matches when its ground targets match).
        """
        missing: list[str] = []
        for handle, tokens, expected_assignment in fact.link_queries:
            answers = self.query(tokens, max_answers=1, timeout=self.verify_timeout)
            found = any(
                handle in answer["handles"]
                and answer["assignments"] == expected_assignment
                for answer in answers
            )
            if not found:
                missing.append(handle)
        return missing

    # ------------------------------------------------------------------ query

    def query(
        self, tokens: list[str], max_answers: int, timeout: float
    ) -> list[dict[str, Any]]:
        """One bounded structural pattern query over the query-engine bus.

        Mirrors the live-verified read-proxy query loop (deploy/das/proxy/
        das_client.py), including the typo workaround for the pinned
        client's ``user_metta_as_query_tokens`` parameter name: the server
        reads ``use_metta_as_query_tokens`` (always false here -- the write
        bridge only issues structural ground templates).
        """
        proxy = PatternMatchingQueryProxy(tokens=tokens)
        proxy.set_parameter("attention_update_flag", False)
        proxy.set_parameter("positive_importance_flag", False)
        proxy.set_parameter("count_flag", False)
        proxy.set_parameter("unique_assignment_flag", False)
        proxy.set_parameter("use_link_template_cache", False)
        proxy.set_parameter("populate_metta_mapping", False)
        proxy.set_parameter("max_bundle_size", min(max_answers, 100))
        proxy.set_parameter("max_answers", max_answers)
        proxy.parameters.pop("user_metta_as_query_tokens", None)
        proxy.set_parameter("use_metta_as_query_tokens", False)

        answers: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout
        with self._query_lock:
            try:
                self._query_bus.issue_bus_command(proxy)
                while not proxy.finished():
                    if time.monotonic() >= deadline:
                        _best_effort_abort(proxy)
                        raise WriteFailure("read-back query timed out")
                    answer = proxy.pop()
                    if answer is None:
                        time.sleep(0.01)
                        continue
                    answers.append(_normalize_answer(answer))
                    if len(answers) >= max_answers:
                        _best_effort_abort(proxy)
                        break
            except WriteFailure:
                raise
            except Exception as exc:
                raise WriteFailure("read-back query failed") from exc
            finally:
                _graceful_shutdown(proxy)
        return answers

    # ------------------------------------------------------------------ plumbing

    def _issue_atomdb(self, proxy: Any) -> None:
        """Issue an atomdb bus command and wait for the broker callback peer.

        The broker announces its server-side proxy node after the bus
        command lands; ``add_atoms``/``delete_atoms`` need that peer id
        before any ``to_remote_peer`` call.
        """
        self._atom_bus.issue_bus_command(proxy)
        node = getattr(proxy, "proxy_node", None)
        if node is None:
            raise WriteFailure("atomdb bus command did not attach a proxy node")
        deadline = time.monotonic() + self.peer_join_timeout
        while not getattr(node, "peer_id", None):
            if time.monotonic() >= deadline:
                raise WriteFailure("atomdb-broker did not attach a callback peer")
            time.sleep(0.05)


def _graceful_shutdown(proxy: Any) -> None:
    try:
        proxy.graceful_shutdown()
    except Exception:
        pass


def _best_effort_abort(proxy: Any) -> None:
    # The pinned client's abort() passes a dict to an API that appends to a
    # list. Call the same read-query control command with the expected type.
    try:
        proxy.to_remote_peer("abort", [])
    except Exception:
        pass


def _hostname_of(endpoint: str, env_name: str) -> str:
    host, separator, _ = endpoint.rpartition(":")
    if not separator or not host:
        raise ValueError(f"{env_name} must be a host:port endpoint, got {endpoint!r}")
    return _validate_hostname(host, env_name)


def _validate_hostname(host: str, env_name: str) -> str:
    if not host or any(character in host for character in ":/[]"):
        raise ValueError(f"{env_name} must be a non-empty hostname, got {host!r}")
    return host


def _install_callback_peer_rewrite(host_by_command: dict[str, str]) -> None:
    """Replace only wildcard hosts advertised by processor-side callback peers.

    Parameterized variant of the read-proxy's rewrite (deploy/das/proxy/
    das_client.py::_install_callback_peer_rewrite): the pinned services bind
    0.0.0.0 and announce wildcard hosts, which are not routable callback
    destinations. The rewrite host is selected per bus command -- invariant
    (c): atomdb callbacks go to the BROKER name, pattern-query callbacks to
    the query-engine name.

    Command matching: the pinned proxies carry ``command`` as the enum value
    ``BusCommand.ATOMDB`` (a ``str``-mixin enum whose ``str()`` yields
    "BusCommand.ATOMDB", NOT "atomdb" -- the first live probe silently
    skipped the rewrite because of exactly that, so normalization is
    load-bearing here); the ServiceBus is constructed with plain strings,
    so both representations are normalized.
    """
    _REWRITE_HOSTS.clear()
    _REWRITE_HOSTS.update(host_by_command)
    manager = DistributedAlgorithmNodeManager
    if getattr(manager, "_omega_write_rewrite_installed", False):
        return

    original = manager.node_joined_network

    def node_joined_network(self: Any, node_id: str) -> None:
        host, separator, port = node_id.rpartition(":")
        if separator and host in {"0.0.0.0", "::", "[::]"} and port.isdigit():
            proxy = getattr(getattr(self, "servicer", None), "proxy", None)
            command = getattr(proxy, "command", "")
            # BusCommand.ATOMDB is a str-mixin enum: str(x) is "BusCommand.ATOMDB"
            # while x.value is "atomdb". Accept both spellings.
            if isinstance(command, str) and command in _REWRITE_HOSTS:
                rewrite_host = _REWRITE_HOSTS[command]
            else:
                rewrite_host = _REWRITE_HOSTS.get(str(getattr(command, "value", "")))
            if rewrite_host:
                node_id = f"{rewrite_host}:{port}"
        original(self, node_id)

    manager.node_joined_network = node_joined_network
    manager._omega_write_rewrite_installed = True


def _install_nested_handle_decoder() -> None:
    """Accept the nested handle vectors emitted by the pinned C++ engine.

    Same wire reality as the read proxy (live-verified 2026-10-18): the
    python client decodes the C++ handle-vector count as a flat handle
    count, so a normal answer makes it interpret the first handle hash as
    the assignment count. Decode the nested format first, then keep the
    dependency decoder as a fallback for its native flat format.
    """
    if getattr(QueryAnswer, "_omega_nested_handle_decoder_installed", False):
        return

    original = QueryAnswer.untokenize

    def untokenize(self: Any, token_str: str) -> None:
        _validate_wire_answer_size(token_str)
        try:
            _untokenize_nested_handle_answer(self, token_str)
        except (ValueError, IndexError):
            original(self, token_str)
        _validate_decoded_answer(self)

    QueryAnswer.untokenize = untokenize
    QueryAnswer._omega_nested_handle_decoder_installed = True


def _untokenize_nested_handle_answer(answer: Any, token_str: str) -> None:
    _validate_wire_answer_size(token_str)

    tokens = token_str.split()
    cursor = 0

    def take() -> str:
        nonlocal cursor
        if cursor >= len(tokens):
            raise ValueError("invalid nested-handle DAS answer: unexpected end")
        value = tokens[cursor]
        cursor += 1
        return value

    answer.strength = float(take())
    answer.importance = float(take())
    vector_count = _bounded_wire_count(take(), _MAX_HANDLE_VECTORS, "handle vectors")
    handles: list[str] = []
    for _ in range(vector_count):
        vector_size = _bounded_wire_count(take(), _MAX_WIRE_HANDLES - len(handles), "handles")
        handles.extend(take() for _ in range(vector_size))

    assignment_count = _bounded_wire_count(take(), _MAX_WIRE_ASSIGNMENTS, "assignments")
    assignment = type(answer.assignment)()
    for _ in range(assignment_count):
        assignment.assign(take(), take())

    # The write bridge never enables populate_metta_mapping; supporting the
    # whitespace-bearing expression encoding would broaden an unused protocol
    # surface, so reject it explicitly.
    if _bounded_wire_count(take(), 0, "MeTTa mappings") != 0 or cursor != len(tokens):
        raise ValueError("invalid nested-handle DAS answer: trailing data")

    answer.handles = handles
    answer.assignment = assignment
    answer.metta_expression = {}


def _validate_wire_answer_size(token_str: str) -> None:
    if not isinstance(token_str, str) or len(token_str.encode("utf-8")) > _MAX_WIRE_ANSWER_BYTES:
        raise ValueError("DAS answer exceeds the proxy decode bound")


def _validate_decoded_answer(answer: Any) -> None:
    handles = getattr(answer, "handles", None)
    assignments = getattr(getattr(answer, "assignment", None), "_mapping", None)
    if not isinstance(handles, list) or len(handles) > _MAX_WIRE_HANDLES:
        raise ValueError("decoded DAS answer has too many handles")
    if not isinstance(assignments, dict) or len(assignments) > _MAX_WIRE_ASSIGNMENTS:
        raise ValueError("decoded DAS answer has too many assignments")
    if getattr(answer, "metta_expression", None):
        raise ValueError("decoded DAS answer contains disabled MeTTa mappings")
    if not math.isfinite(float(answer.strength)) or not math.isfinite(float(answer.importance)):
        raise ValueError("decoded DAS answer contains a non-finite score")


def _bounded_wire_count(token: str, maximum: int, label: str) -> int:
    count = int(token)
    if count < 0 or count > maximum:
        raise ValueError(f"invalid nested-handle DAS answer: {label} count out of bounds")
    return count


def _normalize_answer(answer: Any) -> dict[str, Any]:
    assignments = dict(getattr(answer.assignment, "_mapping", {}))
    return {
        "handles": [_bounded(value) for value in answer.handles[:64]],
        "assignments": {_bounded(key): _bounded(value) for key, value in list(assignments.items())[:64]},
        "strength": float(answer.strength),
        "importance": float(answer.importance),
    }


def _bounded(value: Any) -> str:
    return str(value)[:1024]
