"""Narrow, read-only adapter around the pinned DAS pattern query client."""

from __future__ import annotations

import math
import os
import threading
import time
from typing import Any

from hyperon_das.service_clients import PatternMatchingQueryProxy
from hyperon_das.query_answer import QueryAnswer
from hyperon_das.service_bus.proxy import DistributedAlgorithmNodeManager
from hyperon_das.service_bus.service_bus import ServiceBusSingleton


class QueryFailure(RuntimeError):
    pass


_MAX_WIRE_ANSWER_BYTES = 256 * 1024
_MAX_HANDLE_VECTORS = 64
_MAX_WIRE_HANDLES = 4096
_MAX_WIRE_ASSIGNMENTS = 64


class DasQueryRunner:
    """Run one bounded pattern query at a time over the callback-based DAS bus."""

    def __init__(self) -> None:
        client_endpoint = os.environ["DAS_CLIENT_ENDPOINT"]
        callback_peer_host = os.environ["DAS_CALLBACK_PEER_HOST"]
        lower = int(os.environ["DAS_CALLBACK_PORT_LOWER"])
        upper = int(os.environ["DAS_CALLBACK_PORT_UPPER"])
        query_engine = os.environ["DAS_QUERY_ENGINE"]
        _install_nested_handle_decoder()
        _install_callback_peer_rewrite(callback_peer_host)
        self._bus = ServiceBusSingleton(
            host_id=client_endpoint,
            known_peer=query_engine,
            port_lower=lower,
            port_upper=upper,
        ).get_instance()
        self._lock = threading.Lock()

    def query(self, tokens: list[str], max_answers: int, timeout: float) -> list[dict[str, Any]]:
        proxy = PatternMatchingQueryProxy(tokens=tokens)
        # These values are fixed here, not copied from the HTTP request. The only
        # permitted operation is pattern matching, without attention updates.
        proxy.set_parameter("attention_update_flag", False)
        proxy.set_parameter("positive_importance_flag", False)
        proxy.set_parameter("count_flag", False)
        proxy.set_parameter("unique_assignment_flag", False)
        proxy.set_parameter("use_link_template_cache", False)
        proxy.set_parameter("populate_metta_mapping", False)
        proxy.set_parameter("user_metta_as_query_tokens", False)
        proxy.set_parameter("max_bundle_size", min(max_answers, 100))
        proxy.set_parameter("max_answers", max_answers)

        answers: list[dict[str, Any]] = []
        deadline = time.monotonic() + timeout
        with self._lock:
            try:
                self._bus.issue_bus_command(proxy)
                while not proxy.finished():
                    if time.monotonic() >= deadline:
                        _best_effort_abort(proxy)
                        raise QueryFailure("query timed out")
                    answer = proxy.pop()
                    if answer is None:
                        time.sleep(0.01)
                        continue
                    answers.append(_normalize_answer(answer))
                    if len(answers) >= max_answers:
                        _best_effort_abort(proxy)
                        break
            except QueryFailure:
                raise
            except Exception as exc:
                raise QueryFailure("DAS query failed") from exc
            finally:
                try:
                    proxy.graceful_shutdown()
                except Exception:
                    pass
        return answers


def _install_nested_handle_decoder() -> None:
    """Accept the nested handle vectors emitted by the pinned C++ engine.

    The Python client at the pinned DAS revision decodes the handle-vector
    count as a flat handle count.  A normal C++ answer therefore makes it
    interpret the first handle hash as the assignment count.  Keep the
    matching C++ wire layout first, then retain the dependency decoder as a
    fallback for its native flat format.
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

    # This proxy always disables populate_metta_mapping. Supporting its
    # whitespace-bearing expression encoding here would broaden an unused
    # protocol surface, so reject it explicitly.
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


def _install_callback_peer_rewrite(callback_peer_host: str) -> None:
    """Replace only wildcard hosts advertised by processor-side callback peers.

    The pinned DAS query engine uses its listening endpoint as the host portion
    of every dynamic proxy ID. It must listen on all of its private-network
    interfaces, but 0.0.0.0 is not a routable callback destination. Keep the
    dynamic port and substitute the explicit Compose-private DNS name.
    """
    if not callback_peer_host or any(character in callback_peer_host for character in ":/[]"):
        raise ValueError("DAS_CALLBACK_PEER_HOST must be a non-empty hostname")

    manager = DistributedAlgorithmNodeManager
    if getattr(manager, "_omega_callback_rewrite_installed", False):
        return

    original = manager.node_joined_network

    def node_joined_network(self: Any, node_id: str) -> None:
        host, separator, port = node_id.rpartition(":")
        if separator and host in {"0.0.0.0", "::", "[::]"} and port.isdigit():
            node_id = f"{callback_peer_host}:{port}"
        original(self, node_id)

    manager.node_joined_network = node_joined_network
    manager._omega_callback_rewrite_installed = True


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


def _best_effort_abort(proxy: Any) -> None:
    # The pinned client's abort() passes a dict to an API that appends to a
    # list. Call the same read-query control command with the expected type.
    try:
        proxy.to_remote_peer("abort", [])
    except Exception:
        pass
