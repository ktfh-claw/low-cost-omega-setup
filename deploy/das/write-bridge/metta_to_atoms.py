"""Client-side MeTTa -> atom mapper for the DAS write bridge (v1, data only).

Parses ONE small parenthesized MeTTa fact (e.g.
``(Inheritance (Concept "x402") (Concept "payment-protocol"))``) into the
Node/Link atom objects of the pinned upstream python client
(singnet/das e12573cc, 3rd_party_slots/python_client), following the same
storage conventions the live deployment was verified against (2026-10-18):

- bare symbols become ``Node(type="Symbol", name=<verbatim>)`` (no quotes);
- quoted literals become Symbol nodes with the quotes KEPT in the name
  (``"x402"`` -> name ``"x402"``), matching db_loader/broker storage;
- every (sub-)expression becomes a generic ``Link(type="Expression")`` whose
  targets are the leading element followed by the remaining elements, inner
  expressions referenced by handle -- the generic Expression/Symbol schema
  the AtomDB stores;
- atoms are emitted bottom-up (nodes before the links referencing them),
  de-duplicated by handle, deterministically ordered: the same input always
  yields the same handles (client-side hashing, so client-computed handles
  equal the server-stored ones).

This is a DATA parser: no operators, no evaluation. Only a single expression
is accepted; anything else is rejected with ``MettaParseError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

MAX_DEPTH = 32
MAX_ATOMS = 256
MAX_NAME_CHARS = 512

SYMBOL_TYPE = "Symbol"
EXPRESSION_TYPE = "Expression"

# Label of the verification variable in variable-form link templates: every
# written link is queried with its leading symbol bound to a $variable (the
# only structural form the pinned engine completes for our read-back -- see
# variable_template_tokens).
UNASSIGNED_HANDLE = "unassigned"

# Label of the ALTERNATE oracle's variable: absence is verified through a
# second, differently-shaped pattern (see alt_template_tokens) whose query
# traffic is disjoint from the primary read-back form -- sustained querying
# of the primary form starves the server-side delete apply (live-measured
# iterations 3-6), so the absence verdict needs a pattern the verification
# loop has not kept warm.
ALT_UNASSIGNED_HANDLE = "altassigned"

_WHITESPACE = " \t\r\n"


class MettaParseError(ValueError):
    """The input is not a single, well-formed, bounded MeTTa expression."""


@dataclass(frozen=True)
class Symbol:
    """A leaf: bare symbol or quoted literal; ``name`` is verbatim."""

    name: str


@dataclass(frozen=True)
class Expression:
    """A parenthesized (sub-)expression; ``elements`` are Symbol/Expression."""

    elements: tuple[Any, ...]


def parse_expression(text: str) -> Expression:
    """Parse ``text`` into a single top-level Expression tree."""
    if not isinstance(text, str):
        raise MettaParseError("metta must be a string")
    if not text:
        raise MettaParseError("metta must be a non-empty expression")
    start = _skip_whitespace(text, 0)
    if start >= len(text) or text[start] != "(":
        raise MettaParseError("metta must be a single parenthesized expression")
    pos, tree = _parse_element(text, start, 1)
    pos = _skip_whitespace(text, pos)
    if pos != len(text):
        raise MettaParseError("metta must be exactly one expression (trailing content)")
    if not isinstance(tree, Expression):
        raise MettaParseError("metta must be a single parenthesized expression")
    return tree


def parse_fact(
    text: str,
    *,
    node_factory: Callable[..., Any] | None = None,
    link_factory: Callable[..., Any] | None = None,
) -> "ParsedFact":
    """Parse ``text`` and build its atom list via the pinned client classes.

    ``node_factory``/``link_factory`` default to the pinned client's
    ``Node``/``Link`` (imported lazily so this module can be unit-tested with
    the upstream client stubbed out).
    """
    expression = parse_expression(text)
    node_cls, link_cls = node_factory, link_factory
    if node_cls is None or link_cls is None:
        node_cls, link_cls = _pinned_factories()
    return _build_fact(expression, node_cls, link_cls)


def ground_template_tokens(element: Any) -> list[str]:
    """Structural LINK_TEMPLATE tokens fully grounding ``element``.

    DEPRECATED for verification: variable-free patterns never complete in
    the pinned engine (it answers an error string and the query hangs until
    the client times out -- live-verified 2026-10-19, bridge iteration 2).
    Kept as the nested-spec builder for variable_template_tokens and for
    tests, e.g. ``(Concept "x")`` -> ``["LINK_TEMPLATE", "Expression",
    "2", "NODE", "Symbol", "Concept", "NODE", "Symbol", "\"x\""]``.
    """
    if isinstance(element, Symbol):
        return ["NODE", SYMBOL_TYPE, element.name]
    tokens: list[str] = ["LINK_TEMPLATE", EXPRESSION_TYPE, str(len(element.elements))]
    for child in element.elements:
        tokens.extend(ground_template_tokens(child))
    return tokens


def variable_template_tokens(element: Any) -> list[str]:
    """Structural LINK_TEMPLATE tokens for the completing read-back form.

    The pinned engine never completes variable-free patterns (live-verified
    2026-10-19, bridge iteration 2), so read-back verification cannot use
    fully-ground templates. This form binds the link's LEADING SYMBOL to a
    VARIABLE instead -- the form live-proven in re-eval experiment E1 and by
    this iteration's probe: the engine completes it and the returned
    assignment binds the variable to the leading symbol's actual handle,
    which verify_handles compares against the expected assignment. All
    other positions stay fully ground (nested children as ground
    LINK_TEMPLATE specs), so a match still pins down the exact content.
    """
    if isinstance(element, Symbol):
        return ["NODE", SYMBOL_TYPE, element.name]
    if not isinstance(element.elements[0], Symbol):
        raise MettaParseError(
            "expression must start with a symbol to be verifiable by variable-form query"
        )
    tokens: list[str] = ["LINK_TEMPLATE", EXPRESSION_TYPE, str(len(element.elements))]
    for child in element.elements:
        tokens.extend(ground_template_tokens(child))
    tokens[3:6] = ["VARIABLE", UNASSIGNED_HANDLE]
    return tokens


def alt_template_tokens(element: Any) -> list[str] | None:
    """Alternate-pattern LINK_TEMPLATE tokens for the absence oracle.

    The primary read-back form (variable_template_tokens) is what a cleanup
    loop queries -- and live-measured iterations 3-6 showed the server-side
    delete apply is STARVED by sustained verification traffic: every grace
    window width (30/90/300 s) false-alarmed while the deletion always
    landed, and a light-traffic re-check saw absence at T+7.8 s. The absence
    oracle therefore queries each link through a SECOND, differently-shaped
    pattern (live-validated iteration 6b: leading symbol ground, variable
    in the first non-leading position), so a stale primary match can be
    contradicted by a pattern the verification loop has not kept warm.

    Returns None when the link admits no TIGHT alternate form: 2-arity links
    have no non-leading ground positions left (a variable in the second
    position matches every same-leading-symbol link -- schema-ambiguous on
    a shared DB, live-measured: the live Symbol "Concept" node leads
    hundreds of links), and arity-1 links have no non-leading position at
    all. Such links keep the primary verdict (plus bounded standby
    re-checks).

    For arity >= 3 the pattern is TIGHT: leading symbol ground, variable at
    position 2, every remaining position fully ground -- a match pins the
    link, and parse_fact pins the expected assignment (the variable binds
    to the position-2 element's handle).
    """
    if isinstance(element, Symbol):
        return None
    if not isinstance(element.elements[0], Symbol):
        raise MettaParseError(
            "expression must start with a symbol to be verifiable by alternate-form query"
        )
    if len(element.elements) < 3:
        return None
    tokens: list[str] = ["LINK_TEMPLATE", EXPRESSION_TYPE, str(len(element.elements))]
    tokens.extend(ground_template_tokens(element.elements[0]))
    tokens.extend(["VARIABLE", ALT_UNASSIGNED_HANDLE])
    for child in element.elements[2:]:
        tokens.extend(ground_template_tokens(child))
    return tokens


@dataclass
class ParsedFact:
    """Everything the write/verify/cleanup flows need for one MeTTa fact."""

    expression: Expression
    atoms: list[Any]                 # bottom-up, de-duplicated, deterministic
    handles: list[str]               # parallel to ``atoms``
    top_handle: str                  # handle of the top-level Expression link
    # (link handle, variable-form template, expected assignment), bottom-up
    link_queries: list[tuple[str, list[str], dict[str, str]]]
    # (link handle, alternate-form template, expected assignment) for the
    # links admitting a TIGHT alternate pattern (arity >= 3): the absence
    # oracle. Bottom-up, same dedup order as link_queries.
    link_absence_queries: list[tuple[str, list[str], dict[str, str]]]

    @property
    def link_handles(self) -> list[str]:
        return [handle for handle, _, _ in self.link_queries]


def _pinned_factories() -> tuple[Any, Any]:
    from hyperon_das.commons.atoms import Link, Node

    return Node, Link


def _build_fact(
    expression: Expression, node_cls: Any, link_cls: Any
) -> ParsedFact:
    atoms: list[Any] = []
    seen: dict[str, Any] = {}
    link_queries: list[tuple[str, list[str]]] = []
    link_absence_queries: list[tuple[str, list[str], dict[str, str]]] = []

    def build(element: Any, depth: int) -> str:
        if isinstance(element, Symbol):
            node = node_cls(type=SYMBOL_TYPE, name=element.name)
            _remember(node, node.handle, atoms, seen)
            return node.handle
        targets = [build(child, depth + 1) for child in element.elements]
        link = link_cls(type=EXPRESSION_TYPE, targets=targets)
        if link.handle not in seen:
            _remember(link, link.handle, atoms, seen)
            link_queries.append(
                (link.handle, variable_template_tokens(element), {UNASSIGNED_HANDLE: targets[0]})
            )
            alt_tokens = alt_template_tokens(element)
            if alt_tokens is not None:
                # The alternate oracle's variable sits at position 2: the
                # expected assignment pins that element's handle (a link
                # handle for nested expressions, the quoted node handle for
                # 2-level facts -- the disambiguation iter6b called for).
                link_absence_queries.append(
                    (link.handle, alt_tokens, {ALT_UNASSIGNED_HANDLE: targets[1]})
                )
        return link.handle

    top_handle = build(expression, 1)
    return ParsedFact(
        expression=expression,
        atoms=atoms,
        handles=[atom.handle for atom in atoms],
        top_handle=top_handle,
        link_queries=link_queries,
        link_absence_queries=link_absence_queries,
    )


def _remember(atom: Any, handle: str, atoms: list[Any], seen: dict[str, Any]) -> None:
    if handle not in seen:
        if len(atoms) >= MAX_ATOMS:
            raise MettaParseError(f"expression exceeds the {MAX_ATOMS} atom limit")
        seen[handle] = atom
        atoms.append(atom)


def _skip_whitespace(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in _WHITESPACE:
        pos += 1
    return pos


def _parse_element(text: str, pos: int, depth: int) -> tuple[int, Any]:
    """Parse one element starting at ``pos`` (which must be '(' or a symbol)."""
    if depth > MAX_DEPTH:
        raise MettaParseError(f"expression nesting exceeds the depth limit {MAX_DEPTH}")
    pos = _skip_whitespace(text, pos)
    if pos >= len(text):
        raise MettaParseError("unexpected end of expression")
    if text[pos] == "(":
        return _parse_expression(text, pos, depth)
    return _parse_symbol(text, pos, depth)


def _parse_expression(text: str, pos: int, depth: int) -> tuple[int, Expression]:
    # text[pos] == "("
    pos += 1
    elements: list[Any] = []
    while True:
        pos = _skip_whitespace(text, pos)
        if pos >= len(text):
            raise MettaParseError("unbalanced parentheses (missing ')')")
        if text[pos] == ")":
            pos += 1
            break
        pos, element = _parse_element(text, pos, depth + 1)
        elements.append(element)
    if not elements:
        raise MettaParseError("empty expression '()' is not allowed")
    return pos, Expression(elements=tuple(elements))


def _parse_symbol(text: str, pos: int, depth: int) -> tuple[int, Symbol]:
    start = pos
    if text[pos] == '"':
        pos += 1
        while True:
            if pos >= len(text):
                raise MettaParseError("unterminated quoted literal (missing '\"')")
            char = text[pos]
            if char == '"':
                pos += 1
                break
            if char == "\\":
                raise MettaParseError("escape sequences are not supported in quoted literals")
            if char == "\n" or char == "\r":
                raise MettaParseError("raw line breaks are not allowed inside quoted literals")
            if ord(char) < 0x20:
                raise MettaParseError("control characters are not allowed inside quoted literals")
            pos += 1
        name = text[start:pos]
        _check_name(name, "quoted literal")
        return pos, Symbol(name=name)
    while pos < len(text):
        char = text[pos]
        if char in _WHITESPACE or char in "()":
            break
        if char == '"':
            raise MettaParseError("quoted literal must be separated from the previous symbol")
        if ord(char) < 0x20:
            raise MettaParseError("control characters are not allowed in symbols")
        pos += 1
    name = text[start:pos]
    _check_name(name, "symbol")
    return pos, Symbol(name=name)


def _check_name(name: str, label: str) -> None:
    if len(name) > MAX_NAME_CHARS:
        raise MettaParseError(f"{label} exceeds the {MAX_NAME_CHARS} character limit")
    if label == "symbol" and not name:
        raise MettaParseError("empty symbol is not allowed")
