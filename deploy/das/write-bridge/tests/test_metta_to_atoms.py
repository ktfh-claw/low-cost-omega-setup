"""metta_to_atoms parsing matrix (upstream client stubbed)."""

from __future__ import annotations

import pytest

from conftest import (
    ALT_EXPECTED_ASSIGNMENTS,
    ALT_T_TOP,
    EXPECTED_HANDLES,
    EXPECTED_WIRE_ARGS,
    INNER_PP_HANDLE,
    INNER_X402_HANDLE,
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
    ALT_UNASSIGNED_HANDLE,
    Expression,
    MettaParseError,
    Symbol,
    alt_template_tokens,
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
        assert [handle for handle, _, _ in fact.link_queries] == list(LINK_HANDLES)
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


class TestAltTemplates:
    """The alternate-pattern absence oracle (iteration 7).

    Live-validated iteration 6b: a second, differently-shaped pattern
    (leading symbol GROUND, variable in the first non-leading position)
    completes on the pinned engine with the exact expected assignment --
    the form the cleanup oracle uses, because sustained querying of the
    primary form starves the server-side delete apply.
    """

    def test_alt_form_of_top_link(self):
        # (Inheritance <inner1> <inner2>): leading symbol ground, variable
        # at position 2, remaining positions fully ground. This is exactly
        # the live-validated iter6b P_NEW form.
        fact = parse_fact(X402)
        assert fact.link_absence_queries == [
            (
                TOP_HANDLE,
                ALT_T_TOP,
                {ALT_UNASSIGNED_HANDLE: INNER_X402_HANDLE},
            )
        ]
        assert ALT_EXPECTED_ASSIGNMENTS[tuple(ALT_T_TOP)] == {
            ALT_UNASSIGNED_HANDLE: INNER_X402_HANDLE
        }

    def test_two_arity_links_admit_no_tight_alt(self):
        # (Concept "x402"): a variable in the second position matches every
        # (Concept <anything>) link -- schema-ambiguous on the shared live DB
        # (live-measured 6b) -- so 2-arity links keep the primary verdict.
        fact = parse_fact(X402)
        alt_handles = [handle for handle, _, _ in fact.link_absence_queries]
        assert INNER_X402_HANDLE not in alt_handles
        assert INNER_PP_HANDLE not in alt_handles

    def test_alt_builder_returns_none_for_symbol_and_short_links(self):
        assert alt_template_tokens(Symbol("a")) is None
        assert alt_template_tokens(parse_expression("(a b)").__class__ and parse_expression("(a b)")) is None
        assert alt_template_tokens(parse_expression("(a b c)")) == [
            "LINK_TEMPLATE", "Expression", "3",
            "NODE", "Symbol", "a",
            "VARIABLE", ALT_UNASSIGNED_HANDLE,
            "NODE", "Symbol", "c",
        ]

    def test_alt_form_of_arity_4_links_pins_position_2(self):
        # Position 2 is an inner EXPRESSION: the alt variable binds to that
        # link's handle (the disambiguation iter6b called for).
        fact = parse_fact('(Similarity (Concept "a") (Concept "b") (Concept "c"))')
        (handle, tokens, assignment), = fact.link_absence_queries
        assert handle == fact.top_handle
        assert tokens == [
            "LINK_TEMPLATE", "Expression", "4",
            "NODE", "Symbol", "Similarity",
            "VARIABLE", ALT_UNASSIGNED_HANDLE,
            "LINK_TEMPLATE", "Expression", "2",
            "NODE", "Symbol", "Concept", "NODE", "Symbol", '"b"',
            "LINK_TEMPLATE", "Expression", "2",
            "NODE", "Symbol", "Concept", "NODE", "Symbol", '"c"',
        ]
        # Position 2 = the FIRST (Concept "a") link, not a quoted node.
        first_inner = next(
            h for h, _, _ in fact.link_queries if h != fact.top_handle
        )
        assert assignment == {ALT_UNASSIGNED_HANDLE: first_inner}

    def test_alt_builder_requires_leading_symbol(self):
        with pytest.raises(MettaParseError):
            alt_template_tokens(parse_expression("((a b) c d)"))

    def test_alt_and_primary_forms_are_disjoint_patterns(self):
        # The oracle only works because the alternate tokens differ from the
        # primary variable-form tokens (a stale primary match cannot keep
        # the alternate pattern warm).
        fact = parse_fact(X402)
        primary = {tuple(tokens) for _, tokens, _ in fact.link_queries}
        alt = {tuple(tokens) for _, tokens, _ in fact.link_absence_queries}
        assert alt and not (alt & primary)


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
        # Collect Expression elements bottom-up (same traversal order as
        # parse_fact's link_queries) and compare each link's variable form
        # against ITS OWN ground template: identical apart from the leading
        # symbol spec (3 ground tokens) replaced by the variable (2 tokens).
        def bottom_up(element):
            if isinstance(element, Expression):
                for child in element.elements:
                    yield from bottom_up(child)
                yield element

        fact = parse_fact(X402)
        elements = list(bottom_up(parse_expression(X402)))
        assert len(elements) == len(fact.link_queries)
        for element, (_handle, tokens, _assignment) in zip(elements, fact.link_queries):
            assert tokens == variable_template_tokens(element)
            assert tokens[3:5] == ["VARIABLE", UNASSIGNED_HANDLE]
            ground = ground_template_tokens(element)
            assert len(tokens) == len(ground) - 1
            assert tokens[:3] == ground[:3]
            assert tokens[5:] == ground[6:]

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
