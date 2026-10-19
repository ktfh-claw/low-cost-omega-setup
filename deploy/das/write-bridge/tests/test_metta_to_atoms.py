"""metta_to_atoms parsing matrix (upstream client stubbed)."""

from __future__ import annotations

import pytest

from conftest import (
    EXPECTED_HANDLES,
    EXPECTED_WIRE_ARGS,
    T_INNER_PP,
    T_INNER_X402,
    T_TOP,
    TOP_HANDLE,
    X402_METTA,
    MirrorLink,
    MirrorNode,
)
from metta_to_atoms import (
    MAX_ATOMS,
    MAX_NAME_CHARS,
    UNASSIGNED_HANDLE,
    Expression,
    MettaParseError,
    Symbol,
    ground_template_tokens,
    parse_expression,
    parse_fact,
    variable_template_tokens,
)

X402 = X402_METTA
LINK_HANDLES = EXPECTED_HANDLES[3], EXPECTED_HANDLES[5], EXPECTED_HANDLES[6]


class TestParseExpression:
    def test_canonical_fact(self):
        tree = parse_expression(X402)
        assert isinstance(tree, Expression)
        assert tree.elements[0] == Symbol("Inheritance")
        inner = tree.elements[1]
        assert isinstance(inner, Expression)
        assert inner.elements == (Symbol("Concept"), Symbol('"x402"'))

    def test_bare_symbols(self):
        tree = parse_expression("(isa Concept animal)")
        assert tree.elements == (Symbol("isa"), Symbol("Concept"), Symbol("animal"))

    def test_quoted_string_with_spaces(self):
        tree = parse_expression('(Concept "payment protocol")')
        assert tree.elements == (Symbol("Concept"), Symbol('"payment protocol"'))

    def test_deep_nesting(self):
        tree = parse_expression('(A (B (C "x")))')
        assert tree.elements[1].elements[1].elements == (Symbol("C"), Symbol('"x"'))

    def test_whitespace_tolerance(self):
        assert parse_expression("  ( a  b )\n") == parse_expression("(a b)")

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "Inheritance",
            '"x402"',
            "()",
            "(a",
            "a)",
            "(a b",
            '(a "x',
            "(a) (b)",
            "(a) trailing",
            "!eval",
        ],
    )
    def test_rejected(self, text):
        with pytest.raises(MettaParseError):
            parse_expression(text)

    def test_parens_inside_literals_are_data(self):
        tree = parse_expression('(a "x) b")')
        assert tree.elements == (Symbol("a"), Symbol('"x) b"'))

    def test_quote_must_be_separated_from_symbol(self):
        with pytest.raises(MettaParseError):
            parse_expression('(a"b")')

    def test_backslash_in_literal_rejected(self):
        with pytest.raises(MettaParseError):
            parse_expression('(a "x\\y")')

    def test_raw_newline_in_literal_rejected(self):
        with pytest.raises(MettaParseError):
            parse_expression('(a "x\ny")')

    def test_control_character_rejected(self):
        with pytest.raises(MettaParseError):
            parse_expression("(a\x00b)")

    def test_depth_cap(self):
        with pytest.raises(MettaParseError):
            parse_expression("(" * 100 + "a" + ")" * 100)

    def test_atom_cap(self):
        distinct = " ".join(f"x{index}" for index in range(MAX_ATOMS + 1))
        with pytest.raises(MettaParseError):
            parse_fact("(" + distinct + ")")

    def test_name_cap(self):
        with pytest.raises(MettaParseError):
            parse_expression(f'("{"a" * (MAX_NAME_CHARS + 1)}")')

    def test_non_string_rejected(self):
        with pytest.raises(MettaParseError):
            parse_expression(None)  # type: ignore[arg-type]


class TestParseFact:
    def test_atoms_handles_and_order(self):
        fact = parse_fact(X402)
        assert fact.handles == EXPECTED_HANDLES
        assert fact.top_handle == TOP_HANDLE
        assert [atom.handle for atom in fact.atoms] == EXPECTED_HANDLES
        assert [handle for handle, _ in fact.link_queries] == list(LINK_HANDLES)
        assert all(isinstance(atom, (MirrorNode, MirrorLink)) for atom in fact.atoms)

    def test_atom_types_follow_db_convention(self):
        fact = parse_fact(X402)
        nodes = [atom for atom in fact.atoms if atom.arity() == 0]
        links = [atom for atom in fact.atoms if atom.arity() > 0]
        assert all(atom.type == "Symbol" for atom in nodes)
        assert all(atom.type == "Expression" for atom in links)
        assert nodes[2].name == '"x402"'
        assert nodes[0].name == "Inheritance"
        top = links[-1]
        assert top.targets == [
            EXPECTED_HANDLES[0],
            LINK_HANDLES[0],
            LINK_HANDLES[1],
        ]

    def test_determinism(self):
        first = parse_fact(X402)
        second = parse_fact(X402)
        assert first.handles == second.handles
        assert first.atoms == second.atoms
        assert [list(tokens) for _, tokens, _ in first.link_queries] == [
            list(tokens) for _, tokens, _ in second.link_queries
        ]

    def test_explicit_factories(self):
        fact = parse_fact(X402, node_factory=MirrorNode, link_factory=MirrorLink)
        assert fact.handles == EXPECTED_HANDLES

    def test_dedup_of_repeated_subexpressions(self):
        fact = parse_fact("(A (B) (B))")
        # nodes: A, B; links: (B), top -> 4 unique atoms
        assert len(fact.atoms) == 4
        assert len(fact.link_queries) == 2
        assert fact.top_handle == fact.handles[-1]

    def test_names_longer_than_cap_rejected(self):
        with pytest.raises(MettaParseError):
            parse_fact("(" + "a" * (MAX_NAME_CHARS + 1) + ")")


class TestGroundTemplates:
    def test_symbol(self):
        assert ground_template_tokens(Symbol("Inheritance")) == ["NODE", "Symbol", "Inheritance"]

    def test_inner_links(self):
        fact = parse_fact(X402)
        # Read-back templates are the VARIABLE-FORM (leading symbol bound to
        # $unassigned): variable-free patterns never complete in the pinned
        # engine (live-verified 2026-10-19, bridge iteration 2).
        assert fact.link_queries[0][1] == T_INNER_X402
        assert fact.link_queries[1][1] == T_INNER_PP

    def test_top_link(self):
        fact = parse_fact(X402)
        assert fact.link_queries[2][1] == T_TOP

    def test_expected_assignments_follow_targets(self):
        fact = parse_fact(X402)
        links = [atom for atom in fact.atoms if atom.arity() > 0]
        assert len(links) == len(fact.link_queries)
        for (_handle, _tokens, assignment), link in zip(fact.link_queries, links):
            assert assignment == {UNASSIGNED_HANDLE: link.targets[0]}

    def test_variable_form_binds_leading_symbol_only(self):
        fact = parse_fact(X402)
        for _handle, tokens, assignment in fact.link_queries:
            assert tokens[3:5] == ["VARIABLE", UNASSIGNED_HANDLE]
            ground = ground_template_tokens(fact.expression)
            # Same shape as the fully-ground template apart from the leading
            # symbol spec, which the variable replaces.
            assert len(tokens) == len(ground)
            assert tokens[:3] == ground[:3]
            assert tokens[5:] == ground[5:]

    def test_variable_form_requires_leading_symbol(self):
        with pytest.raises(MettaParseError):
            parse_fact('((a b) c)')

    def test_wire_args_match_pinned_token_protocol(self):
        fact = parse_fact(X402)
        args = []
        for atom in fact.atoms:
            args.append("NODE" if atom.arity() == 0 else "LINK")
            atom.tokenize(args)
        assert args == EXPECTED_WIRE_ARGS
