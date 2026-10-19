"""Test fixtures: the pinned upstream python client is STUBBED here.

No network, no docker: ``hyperon_das`` is replaced in ``sys.modules`` by
in-process fakes that mirror the pinned client's protocol behavior
(singnet/das e12573cc, 3rd_party_slots/python_client). The mirror atom
classes implement the same handle formulas as the pinned ``hyperon_das.hasher``
(md5 of "type name" for nodes, md5 of "md5(type) target..." for links), so
the expected handles embedded in the tests (computed with the real pinned
client) validate the whole mapping.
"""

from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- mirror atoms
# Mirror of the pinned hyperon_das.commons.atoms Node/Link (constructor
# surface, handle formula, tokenize wire format, equality semantics).


class MirrorNode:
    def __init__(self, type=None, name=None, is_toplevel=False, custom_attributes=None, **_):
        if not type or not name:
            raise ValueError("'type' and 'name' are required")
        self.type = type
        self._name = name
        self.is_toplevel = is_toplevel
        self.custom_attributes = custom_attributes if custom_attributes is not None else {}

    @property
    def name(self):
        return self._name

    @property
    def handle(self):
        return _md5(f"{self.type} {self.name}")

    def arity(self):
        return 0

    def tokenize(self, output):
        output.append(self.type)
        output.append("true" if self.is_toplevel else "false")
        output.append("0")
        output.append(self.name)

    def __eq__(self, other):
        return (
            isinstance(other, MirrorNode)
            and self.name == other.name
            and self.type == other.type
            and self.is_toplevel == other.is_toplevel
            and self.custom_attributes == other.custom_attributes
        )

    def __ne__(self, other):
        return not self.__eq__(other)


class MirrorLink:
    def __init__(self, type=None, targets=None, is_toplevel=False, custom_attributes=None, **_):
        if not type or not targets:
            raise ValueError("'type' and 'targets' are required")
        self.type = type
        self._targets = list(targets)
        self.is_toplevel = is_toplevel
        self.custom_attributes = custom_attributes if custom_attributes is not None else {}

    @property
    def targets(self):
        return self._targets

    def arity(self):
        return len(self._targets)

    @property
    def handle(self):
        return _md5(" ".join([_md5(self.type), *self._targets]))

    def tokenize(self, output):
        output.append(self.type)
        output.append("true" if self.is_toplevel else "false")
        output.append("0")
        output.append(str(len(self._targets)))
        output.extend(self._targets)

    def __eq__(self, other):
        return (
            isinstance(other, MirrorLink)
            and self.targets == other.targets
            and self.type == other.type
            and self.is_toplevel == other.is_toplevel
            and self.custom_attributes == other.custom_attributes
        )

    def __ne__(self, other):
        return not self.__eq__(other)


# ---------------------------------------------------------------- wire stubs


class FakeAssignment:
    def __init__(self):
        self._mapping = {}

    def assign(self, label, value):
        if label in self._mapping:
            return self._mapping[label] == value
        self._mapping[label] = value
        return True


class FakeQueryAnswer:
    """Mirror of the pinned QueryAnswer (flat-format original untokenize)."""

    def __init__(self):
        self.handles = []
        self.metta_expression = {}
        self.importance = 0.0
        self.strength = 0.0
        self.assignment = FakeAssignment()

    def untokenize(self, token_str):
        tokens = token_str.strip().split()
        cursor = 0

        def take():
            nonlocal cursor
            value = tokens[cursor]
            cursor += 1
            return value

        self.strength = float(take())
        self.importance = float(take())
        count = int(take())
        if count < 0:
            raise ValueError("negative handle count")
        self.handles = [take() for _ in range(count)]
        assignments = int(take())
        if assignments < 0:
            raise ValueError("negative assignment count")
        self.assignment = FakeAssignment()
        for _ in range(assignments):
            self.assignment.assign(take(), take())
        mappings = int(take())
        if mappings < 0:
            raise ValueError("negative metta mapping count")
        for _ in range(mappings):
            self.metta_expression[take()] = take()
        if cursor != len(tokens):
            raise ValueError("extra data after parsing")


class FakeAtomDBProxy:
    """Mirror of the pinned AtomDBProxy (client-side surface + wire calls)."""

    COMMAND_SIZE_LIMIT = 5000
    ADD_ATOMS = "add_atoms"

    def __init__(self):
        self.command = "atomdb"
        self.args = []
        self.parameters = {}
        self.proxy_port = 0
        self.proxy_node = None
        self.requestor_id = None
        self.serial = None
        self.remote_calls = []
        self.shutdown_count = 0

    def pack_command_line_args(self):
        self.args = [str(len(self.parameters))]

    def add_atoms(self, atoms, use_streaming=False):
        args = []
        handles = []
        for atom in atoms:
            args.append("NODE" if atom.arity() == 0 else "LINK")
            atom.tokenize(args)
            handles.append(atom.handle)
            if len(args) > self.COMMAND_SIZE_LIMIT or atom == atoms[-1]:
                self.to_remote_peer(self.ADD_ATOMS, args)
                args = []
        return handles

    def to_remote_peer(self, command, args):
        self.remote_calls.append((command, list(args)))

    def graceful_shutdown(self):
        self.shutdown_count += 1


class FakePatternMatchingQueryProxy:
    """Mirror of the pinned PatternMatchingQueryProxy (params + answers)."""

    COUNT = "count"
    ANSWER_BUNDLE = "answer_bundle"

    def __init__(self, tokens, context=""):
        self.command = "pattern_matching_query"
        self.tokens = list(tokens)
        self.context = context
        self.parameters = {
            "user_metta_as_query_tokens": False,
            "max_answers": 0,
        }
        self.answer_queue = []
        self.abort_flag = False
        self.command_finished_flag = False
        self.proxy_port = 0
        self.proxy_node = None
        self.requestor_id = None
        self.serial = None
        self.remote_calls = []
        self.shutdown_count = 0

    def set_parameter(self, key, value):
        self.parameters[key] = value

    def pack_command_line_args(self):
        self.args = [str(len(self.parameters))]

    def pop(self):
        if self.abort_flag:
            return FakeQueryAnswer()
        return self.answer_queue.pop(0) if self.answer_queue else None

    def finished(self):
        return self.abort_flag or (self.command_finished_flag and not self.answer_queue)

    def process_message(self, msg):
        for token in msg:
            if token == "finished":
                self.command_finished_flag = True
            elif token == "abort":
                self.abort_flag = True
            elif token in (self.COUNT, self.ANSWER_BUNDLE):
                continue
            else:
                answer = FakeQueryAnswer()
                answer.untokenize(token)
                self.answer_queue.append(answer)

    def to_remote_peer(self, command, args):
        self.remote_calls.append((command, list(args)))

    def graceful_shutdown(self):
        self.shutdown_count += 1


class FakeServiceBus:
    """Records the (known_peer, commands) a runner wires it with."""

    instances = []

    def __init__(self, host_id, known_peer, commands, port_lower, port_upper):
        self.host_id = host_id
        self.known_peer = known_peer
        self.commands = list(commands)
        self.port_lower = port_lower
        self.port_upper = port_upper
        self.issued = []
        FakeServiceBus.instances.append(self)

    def issue_bus_command(self, proxy):
        self.issued.append(proxy)


class FakeDistributedAlgorithmNodeManager:
    """Mirror of the pinned manager (peer_id bookkeeping only)."""

    def __init__(self, node_id=None, server_id=None, proxy=None):
        self.node_id = node_id
        self.server_id = server_id
        self.servicer = types.SimpleNamespace(proxy=proxy)
        self.peer_id = None

    def node_joined_network(self, node_id):
        self.peer_id = node_id


def _module(name: str, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)
    return sys.modules[name]


def _install_stubs():
    _module("hyperon_das")
    _module("hyperon_das.commons")
    _module("hyperon_das.commons.atoms", Atom=object, Node=MirrorNode, Link=MirrorLink)
    _module(
        "hyperon_das.query_answer",
        Assignment=FakeAssignment,
        QueryAnswer=FakeQueryAnswer,
    )
    _module("hyperon_das.service_bus")
    _module(
        "hyperon_das.service_bus.proxy",
        DistributedAlgorithmNodeManager=FakeDistributedAlgorithmNodeManager,
    )
    _module("hyperon_das.service_bus.service_bus", ServiceBus=FakeServiceBus)
    _module(
        "hyperon_das.service_clients",
        AtomDBProxy=FakeAtomDBProxy,
        PatternMatchingQueryProxy=FakePatternMatchingQueryProxy,
    )


_install_stubs()

# ---------------------------------------------------------------- script buses


class ScriptedAtomBus:
    """Atom bus fake: attaches a broker callback peer on issue."""

    def __init__(self, peer_id="atomdb-broker:47001", attach_peer=True):
        self.peer_id = peer_id
        self.attach_peer = attach_peer
        self.issued = []

    def issue_bus_command(self, proxy):
        self.issued.append(proxy)
        proxy.requestor_id = "write-bridge:43999"
        proxy.serial = len(self.issued)
        proxy.proxy_port = 43300 + len(self.issued)
        proxy.pack_command_line_args()
        proxy.proxy_node = types.SimpleNamespace(
            peer_id=self.peer_id if self.attach_peer else None,
            node_id=f"write-bridge:{proxy.proxy_port}",
        )


class ScriptedQueryBus:
    """Query bus fake: delivers scripted nested-handle wire answers.

    ``answers_by_query`` maps a token tuple to a list of answer token
    strings; a query with no entry gets no answers. ``finish`` controls
    whether the server announces completion.
    """

    def __init__(self, answers_by_query=None, finish=True):
        self.answers_by_query = {tuple(k): list(v) for k, v in (answers_by_query or {}).items()}
        self.finish = finish
        self.issued = []

    def issue_bus_command(self, proxy):
        self.issued.append(proxy)
        proxy.requestor_id = "write-bridge:43999"
        proxy.serial = len(self.issued)
        proxy.proxy_port = 43310 + len(self.issued)
        proxy.pack_command_line_args()
        proxy.proxy_node = types.SimpleNamespace(
            peer_id="query-engine:42456",
            node_id=f"write-bridge:{proxy.proxy_port}",
        )
        message = list(self.answers_by_query.get(tuple(proxy.tokens), []))
        if self.finish:
            message.append("finished")
        proxy.process_message(message)


def nested_answer_token(handle: str, assignments: dict[str, str] | None = None) -> str:
    """One nested-handle answer (C++ wire format) with optional assignments."""
    assignment_tokens: list[str] = []
    for label, value in (assignments or {}).items():
        assignment_tokens.extend([label, value])
    return (
        f"1.0000000000 0.5000000000 1 1 {handle} "
        f"{len(assignments or {})} {' '.join(assignment_tokens)} 0"
    )


# ---------------------------------------------------------------- env fixture

BRIDGE_ENV = {
    "DAS_CLIENT_ENDPOINT": "write-bridge:43999",
    "DAS_BROKER_ENDPOINT": "atomdb-broker:40007",
    "DAS_BROKER_PEER_HOST": "atomdb-broker",
    "DAS_QUERY_ENGINE": "query-engine:40002",
    "DAS_CALLBACK_PORT_LOWER": "43300",
    "DAS_CALLBACK_PORT_UPPER": "43331",
}

# The canonical canary fact and the values the REAL pinned client
# (singnet/das e12573cc) produces for it.
X402_METTA = '(Inheritance (Concept "x402") (Concept "payment-protocol"))'
EXPECTED_HANDLES = [
    "9028a696c1b6d3d9ff8c4f496da77378",  # Symbol Inheritance
    "5e50ef7542bb0fde52aed0d841335790",  # Symbol Concept
    "e2f6cbeea42509ef822009139fedfeda",  # Symbol "x402" (quotes kept)
    "454f6502e71d6f7e1c52b1e4f308cb15",  # (Concept "x402")
    "3837420c25c1ce0c66ea8c9688f7e267",  # Symbol "payment-protocol"
    "42f691261c2ee66fb6fbc72096185de0",  # (Concept "payment-protocol")
    "67293e82ab2162d2d9d5a1578670f678",  # top-level link
]
TOP_HANDLE = EXPECTED_HANDLES[-1]
INNER_X402_HANDLE = EXPECTED_HANDLES[3]
INNER_PP_HANDLE = EXPECTED_HANDLES[5]

EXPECTED_WIRE_ARGS = [
    "NODE", "Symbol", "false", "0", "Inheritance",
    "NODE", "Symbol", "false", "0", "Concept",
    "NODE", "Symbol", "false", "0", '"x402"',
    "LINK", "Expression", "false", "0", "2",
    "5e50ef7542bb0fde52aed0d841335790", "e2f6cbeea42509ef822009139fedfeda",
    "NODE", "Symbol", "false", "0", '"payment-protocol"',
    "LINK", "Expression", "false", "0", "2",
    "5e50ef7542bb0fde52aed0d841335790", "3837420c25c1ce0c66ea8c9688f7e267",
    "LINK", "Expression", "false", "0", "3",
    "9028a696c1b6d3d9ff8c4f496da77378",
    "454f6502e71d6f7e1c52b1e4f308cb15",
    "42f691261c2ee66fb6fbc72096185de0",
]

GROUND_INNER_X402 = ["LINK_TEMPLATE", "Expression", "2", "NODE", "Symbol", "Concept", "NODE", "Symbol", '"x402"']
GROUND_INNER_PP = ["LINK_TEMPLATE", "Expression", "2", "NODE", "Symbol", "Concept", "NODE", "Symbol", '"payment-protocol"']
# Variable-form verification templates (leading symbol bound to $unassigned,
# all other positions fully ground) -- the only structural form the pinned
# engine completes (live-verified 2026-10-19, bridge iteration 2).
T_INNER_X402 = ["LINK_TEMPLATE", "Expression", "2", "VARIABLE", "unassigned", "NODE", "Symbol", '"x402"']
T_INNER_PP = ["LINK_TEMPLATE", "Expression", "2", "VARIABLE", "unassigned", "NODE", "Symbol", '"payment-protocol"']
T_TOP = ["LINK_TEMPLATE", "Expression", "3", "VARIABLE", "unassigned", *GROUND_INNER_X402, *GROUND_INNER_PP]
# The assignment each link's read-back answer must carry: the variable bound
# to the leading symbol's handle.
EXPECTED_ASSIGNMENTS = {
    tuple(T_INNER_X402): {"unassigned": "5e50ef7542bb0fde52aed0d841335790"},
    tuple(T_INNER_PP): {"unassigned": "5e50ef7542bb0fde52aed0d841335790"},
    tuple(T_TOP): {"unassigned": "9028a696c1b6d3d9ff8c4f496da77378"},
}


@pytest.fixture()
def bridge_env(monkeypatch):
    for key, value in BRIDGE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DAS_VERIFY_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("DAS_PEER_JOIN_TIMEOUT_SECONDS", "5")
    return dict(BRIDGE_ENV)
