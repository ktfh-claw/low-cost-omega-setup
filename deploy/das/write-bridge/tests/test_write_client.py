"""DasWriteRunner logic with the upstream client stubbed (fake proxies)."""

from __future__ import annotations

import types

import pytest

import write_client
from conftest import (
    EXPECTED_ASSIGNMENTS,
    EXPECTED_HANDLES,
    EXPECTED_WIRE_ARGS,
    INNER_PP_HANDLE,
    INNER_X402_HANDLE,
    T_INNER_PP,
    T_INNER_X402,
    T_TOP,
    TOP_HANDLE,
    X402_METTA,
    FakeDistributedAlgorithmNodeManager,
    FakeQueryAnswer,
    FakeServiceBus,
    ScriptedAtomBus,
    ScriptedQueryBus,
    nested_answer_token,
)
from metta_to_atoms import MettaParseError, parse_fact
from write_client import DELETE_CHUNK_SIZE, DasWriteRunner, WriteFailure

X402 = X402_METTA
ALL_LINKS_ANSWERS = {
    tuple(T_INNER_X402): [nested_answer_token(INNER_X402_HANDLE, EXPECTED_ASSIGNMENTS[tuple(T_INNER_X402)])],
    tuple(T_INNER_PP): [nested_answer_token(INNER_PP_HANDLE, EXPECTED_ASSIGNMENTS[tuple(T_INNER_PP)])],
    tuple(T_TOP): [nested_answer_token(TOP_HANDLE, EXPECTED_ASSIGNMENTS[tuple(T_TOP)])],
}


def make_runner(atom_bus=None, query_bus=None):
    return DasWriteRunner(
        atom_bus=atom_bus or ScriptedAtomBus(),
        query_bus=query_bus or ScriptedQueryBus(),
    )


class TestBusConstruction:
    def test_buses_join_their_peer_directly_with_disjoint_commands(self, bridge_env):
        FakeServiceBus.instances.clear()
        DasWriteRunner()
        atom_bus, query_bus = FakeServiceBus.instances
        # Invariant (b): the atom bus can ONLY route atomdb to the broker,
        # the query bus can ONLY route pattern queries to the query engine.
        assert atom_bus.known_peer == "atomdb-broker:40007"
        assert atom_bus.commands == ["atomdb"]
        assert query_bus.known_peer == "query-engine:40002"
        assert query_bus.commands == ["pattern_matching_query"]
        assert atom_bus.host_id == query_bus.host_id == "write-bridge:43999"

    def test_missing_env_is_required(self, bridge_env, monkeypatch):
        monkeypatch.delenv("DAS_BROKER_ENDPOINT")
        with pytest.raises(KeyError):
            DasWriteRunner()

    def test_query_engine_must_be_host_port(self, bridge_env, monkeypatch):
        monkeypatch.setenv("DAS_QUERY_ENGINE", "query-engine")
        with pytest.raises(ValueError, match="DAS_QUERY_ENGINE"):
            DasWriteRunner()

    def test_broker_peer_host_must_be_hostname(self, bridge_env, monkeypatch):
        monkeypatch.setenv("DAS_BROKER_PEER_HOST", "atomdb-broker:40007")
        with pytest.raises(ValueError, match="DAS_BROKER_PEER_HOST"):
            DasWriteRunner()


class TestCallbackPeerRewrite:
    def test_rewrite_dispatches_per_command(self, bridge_env):
        make_runner()  # installs the parameterized rewrite
        for command, expected in (
            ("atomdb", "atomdb-broker"),
            ("pattern_matching_query", "query-engine"),
        ):
            manager = FakeDistributedAlgorithmNodeManager()
            manager.servicer = types.SimpleNamespace(
                proxy=types.SimpleNamespace(command=command)
            )
            manager.node_joined_network("0.0.0.0:47123")
            assert manager.peer_id == f"{expected}:47123"

    def test_str_enum_command_names_are_normalized(self, bridge_env):
        # The pinned proxies carry command as BusCommand.ATOMDB -- a str-mixin
        # enum whose str() is "BusCommand.ATOMDB" (live probe 1 root cause:
        # the rewrite silently never fired). The rewritten manager must
        # normalize both the enum spelling and the plain .value form.
        make_runner()
        for command in ("BusCommand.ATOMDB", "BusCommand.PATTERN_MATCHING_QUERY"):
            manager = FakeDistributedAlgorithmNodeManager()
            manager.servicer = types.SimpleNamespace(
                proxy=types.SimpleNamespace(command=command)
            )
            manager.node_joined_network("0.0.0.0:47123")
            assert manager.peer_id == f"{'atomdb-broker' if 'ATOMDB' in command else 'query-engine'}:47123"

    def test_non_wildcard_hosts_are_kept(self, bridge_env):
        make_runner()
        manager = FakeDistributedAlgorithmNodeManager()
        manager.servicer = types.SimpleNamespace(proxy=types.SimpleNamespace(command="atomdb"))
        manager.node_joined_network("10.0.0.9:47123")
        assert manager.peer_id == "10.0.0.9:47123"

    def test_unknown_command_and_bad_ports_are_kept(self, bridge_env):
        make_runner()
        manager = FakeDistributedAlgorithmNodeManager()
        manager.servicer = types.SimpleNamespace(proxy=types.SimpleNamespace(command="other"))
        manager.node_joined_network("0.0.0.0:47123")
        assert manager.peer_id == "0.0.0.0:47123"
        manager.servicer.proxy = types.SimpleNamespace(command="atomdb")
        manager.node_joined_network("0.0.0.0:not-a-port")
        assert manager.peer_id == "0.0.0.0:not-a-port"


class TestWrite:
    def test_write_without_verify(self, bridge_env):
        atom_bus, query_bus = ScriptedAtomBus(), ScriptedQueryBus()
        runner = make_runner(atom_bus, query_bus)
        result = runner.write(X402, verify=False)
        assert result == {
            "written": EXPECTED_HANDLES,
            "verified": None,
            "missing": [],
            "top_handle": TOP_HANDLE,
        }
        # One atomdb proxy, one add_atoms command with the pinned wire format.
        assert len(atom_bus.issued) == 1
        proxy = atom_bus.issued[0]
        assert proxy.remote_calls == [("add_atoms", EXPECTED_WIRE_ARGS)]
        assert proxy.shutdown_count == 1
        assert query_bus.issued == []

    def test_write_verified(self, bridge_env):
        atom_bus = ScriptedAtomBus()
        query_bus = ScriptedQueryBus(ALL_LINKS_ANSWERS)
        runner = make_runner(atom_bus, query_bus)
        result = runner.write(X402, verify=True)
        assert result == {
            "written": EXPECTED_HANDLES,
            "verified": True,
            "missing": [],
            "top_handle": TOP_HANDLE,
        }
        # One variable-form query per written link, bottom-up.
        assert [proxy.tokens for proxy in query_bus.issued] == [
            T_INNER_X402,
            T_INNER_PP,
            T_TOP,
        ]
        for proxy in query_bus.issued:
            assert proxy.parameters["use_metta_as_query_tokens"] is False
            assert "user_metta_as_query_tokens" not in proxy.parameters
            assert proxy.parameters["max_answers"] == 1
            assert proxy.parameters["attention_update_flag"] is False
            assert proxy.parameters["populate_metta_mapping"] is False

    def test_write_verified_requires_matching_assignment(self, bridge_env):
        # Wrong assignment (variable bound to a different handle) must count
        # as missing even when the link handle appears in the answer.
        wrong_assignment = {**ALL_LINKS_ANSWERS}
        wrong_assignment[tuple(T_TOP)] = [
            nested_answer_token(TOP_HANDLE, {"unassigned": "f" * 32})
        ]
        runner = make_runner(query_bus=ScriptedQueryBus(wrong_assignment))
        result = runner.write(X402, verify=True)
        assert result["verified"] is False
        assert result["missing"] == [TOP_HANDLE]

    def test_write_reports_missing_links(self, bridge_env):
        partial = dict(ALL_LINKS_ANSWERS)
        partial.pop(tuple(T_TOP))
        query_bus = ScriptedQueryBus(partial)
        runner = make_runner(query_bus=query_bus)
        result = runner.write(X402, verify=True)
        assert result["verified"] is False
        assert result["missing"] == [TOP_HANDLE]
        assert result["written"] == EXPECTED_HANDLES

    def test_verify_failure_carries_handles(self, bridge_env, monkeypatch):
        monkeypatch.setenv("DAS_VERIFY_TIMEOUT_SECONDS", "0.05")
        runner = make_runner(query_bus=ScriptedQueryBus(finish=False))
        with pytest.raises(WriteFailure) as excinfo:
            runner.write(X402, verify=True)
        assert excinfo.value.handles == EXPECTED_HANDLES
        assert "read-back verification failed" in str(excinfo.value)

    def test_broker_peer_timeout_is_a_write_failure(self, bridge_env, monkeypatch):
        monkeypatch.setenv("DAS_PEER_JOIN_TIMEOUT_SECONDS", "0.05")
        runner = make_runner(atom_bus=ScriptedAtomBus(attach_peer=False))
        with pytest.raises(WriteFailure) as excinfo:
            runner.write(X402, verify=False)
        assert excinfo.value.handles == EXPECTED_HANDLES
        assert "atomdb write failed" in str(excinfo.value)

    def test_parse_errors_propagate(self, bridge_env):
        runner = make_runner()
        with pytest.raises(MettaParseError):
            runner.write("(Inheritance")

    def test_verify_handles_direct(self, bridge_env):
        fact = parse_fact(X402)
        runner = make_runner(query_bus=ScriptedQueryBus(ALL_LINKS_ANSWERS))
        assert runner.verify_handles(fact) == []
        partial = dict(ALL_LINKS_ANSWERS)
        partial.pop(tuple(T_INNER_X402))
        partial.pop(tuple(T_TOP))
        runner = make_runner(query_bus=ScriptedQueryBus(partial))
        assert runner.verify_handles(fact) == [INNER_X402_HANDLE, TOP_HANDLE]


class TestProvenanceV4:
    PROV = {
        "ref": "https://example.com/source.md",
        "git_commit": "git:" + "a" * 40,
        "blob_sha256": "b" * 64,
    }
    TV = {"strength": 0.9, "confidence": 0.8}

    def test_valid_v4_provenance_shape_accepted(self, bridge_env):
        atom_bus = ScriptedAtomBus()
        runner = make_runner(atom_bus=atom_bus)
        result = runner.write(X402, verify=False, provenance=self.PROV)
        assert result["top_handle"] == TOP_HANDLE

    @pytest.mark.parametrize(
        "provenance",
        [
            {"ref": "https://a.com"},  # missing keys
            {"ref": "https://a.com", "git_commit": "git:" + "a" * 40},  # missing blob_sha256
            {**PROV, "fetched_at": "x"},  # extra key
            {**PROV, "url": "https://a.com"},  # legacy key
            "not-a-dict",
        ],
    )
    def test_provenance_shape_errors(self, bridge_env, provenance):
        runner = make_runner()
        with pytest.raises(WriteFailure) as excinfo:
            runner.write(X402, verify=False, provenance=provenance)
        assert str(excinfo.value) == "provenance must contain ref, git_commit and blob_sha256"

    @pytest.mark.parametrize(
        "provenance",
        [
            {**PROV, "ref": "relative/path"},
            {**PROV, "ref": "https://a.com/a b"},  # whitespace
            {**PROV, "ref": "x" * 481},  # too long
            {**PROV, "ref": ""},
            {"ref": 123, "git_commit": "git:" + "a" * 40, "blob_sha256": "b" * 64},
        ],
    )
    def test_provenance_ref_errors(self, bridge_env, provenance):
        runner = make_runner()
        with pytest.raises(WriteFailure) as excinfo:
            runner.write(X402, verify=False, provenance=provenance)
        assert str(excinfo.value) == "provenance ref must be an http(s) URL or an allowed absolute path"

    @pytest.mark.parametrize(
        "provenance",
        [
            {**PROV, "git_commit": "not-git-prefixed"},
            {**PROV, "git_commit": "git:" + "z" * 40},
            {**PROV, "git_commit": "git:" + "a" * 39},
        ],
    )
    def test_provenance_git_commit_errors(self, bridge_env, provenance):
        runner = make_runner()
        with pytest.raises(WriteFailure) as excinfo:
            runner.write(X402, verify=False, provenance=provenance)
        assert str(excinfo.value) == 'provenance git_commit must be "git:" + 40 hex chars'

    @pytest.mark.parametrize(
        "provenance",
        [
            {**PROV, "blob_sha256": "B" * 64},  # uppercase
            {**PROV, "blob_sha256": "b" * 63},
            {**PROV, "blob_sha256": "z" * 64},
            {**PROV, "blob_sha256": 123},
        ],
    )
    def test_provenance_blob_sha_errors(self, bridge_env, provenance):
        runner = make_runner()
        with pytest.raises(WriteFailure) as excinfo:
            runner.write(X402, verify=False, provenance=provenance)
        assert str(excinfo.value) == "provenance blob_sha256 must be 64 lowercase hex characters"

    def test_validation_error_leaves_the_bus_untouched(self, bridge_env):
        atom_bus = ScriptedAtomBus()
        runner = make_runner(atom_bus=atom_bus)
        with pytest.raises(WriteFailure):
            runner.write(X402, verify=False, provenance={"ref": "x"})
        assert atom_bus.issued == []

    def test_decorate_top_link_sets_exactly_the_v4_attributes(self, bridge_env):
        fact = parse_fact(X402)
        expected = {
            "metta_expression": X402,
            "provenance_ref": self.PROV["ref"],
            "provenance_git_commit": self.PROV["git_commit"],
            "provenance_blob_sha256": self.PROV["blob_sha256"],
            "stv_strength": self.TV["strength"],
            "stv_confidence": self.TV["confidence"],
        }
        write_client._decorate_top_link(fact, X402, dict(self.PROV), dict(self.TV))
        for atom in fact.atoms:
            if atom.handle == TOP_HANDLE:
                assert atom.custom_attributes == expected
            else:
                assert atom.custom_attributes == {}

    def test_decorate_top_link_without_provenance_or_tv(self, bridge_env):
        fact = parse_fact(X402)
        write_client._decorate_top_link(fact, X402, None, None)
        for atom in fact.atoms:
            if atom.handle == TOP_HANDLE:
                assert atom.custom_attributes == {"metta_expression": X402}
            else:
                assert atom.custom_attributes == {}

    def test_write_with_provenance_sends_only_fact_atoms(self, bridge_env):
        # NO companion WriteProvenance atoms: the single add_atoms batch is
        # the exact fact-atoms wire format.
        atom_bus = ScriptedAtomBus()
        query_bus = ScriptedQueryBus()
        runner = make_runner(atom_bus, query_bus)
        result = runner.write(X402, verify=False, provenance=self.PROV)
        assert result["written"] == EXPECTED_HANDLES
        assert len(atom_bus.issued) == 1
        assert atom_bus.issued[0].remote_calls == [("add_atoms", EXPECTED_WIRE_ARGS)]

    def test_write_with_provenance_queries_only_fact_links(self, bridge_env):
        # Exactly the 3 fact link queries — no prov_fact query.
        query_bus = ScriptedQueryBus(ALL_LINKS_ANSWERS)
        runner = make_runner(query_bus=query_bus)
        result = runner.write(X402, verify=True, provenance=self.PROV)
        assert [proxy.tokens for proxy in query_bus.issued] == [
            T_INNER_X402,
            T_INNER_PP,
            T_TOP,
        ]
        assert result["verified"] is True

    def test_result_top_handle_in_both_verify_paths(self, bridge_env):
        runner = make_runner()
        unverified = runner.write(X402, verify=False, provenance=self.PROV)
        assert unverified["top_handle"] == TOP_HANDLE
        assert "provenance_link" not in unverified
        runner = make_runner(query_bus=ScriptedQueryBus(ALL_LINKS_ANSWERS))
        verified = runner.write(X402, verify=True, provenance=self.PROV)
        assert verified["top_handle"] == TOP_HANDLE
        assert "provenance_link" not in verified


class TestDelete:
    def _handles(self, count):
        return [f"{index:032x}" for index in range(1, count + 1)]

    def test_delete_chunks_follow_upstream_wire_format(self, bridge_env):
        atom_bus = ScriptedAtomBus()
        runner = make_runner(atom_bus=atom_bus)
        handles = self._handles(120)
        runner.delete_atoms(handles)
        proxy = atom_bus.issued[0]
        assert [command for command, _ in proxy.remote_calls] == [
            "delete_atoms",
            "delete_atoms",
            "delete_atoms",
        ]
        chunks = [args for _, args in proxy.remote_calls]
        assert [len(chunk) for chunk in chunks] == [
            DELETE_CHUNK_SIZE + 1,
            DELETE_CHUNK_SIZE + 1,
            20 + 1,
        ]
        assert chunks[0][:DELETE_CHUNK_SIZE] == handles[:DELETE_CHUNK_SIZE]
        assert chunks[1][:DELETE_CHUNK_SIZE] == handles[DELETE_CHUNK_SIZE : 2 * DELETE_CHUNK_SIZE]
        assert chunks[2] == handles[2 * DELETE_CHUNK_SIZE :] + ["0"]
        assert all(chunk[-1] == "0" for chunk in chunks)

    def test_delete_link_targets_flag(self, bridge_env):
        atom_bus = ScriptedAtomBus()
        runner = make_runner(atom_bus=atom_bus)
        runner.delete_atoms(["a" * 32], delete_link_targets=True)
        assert atom_bus.issued[0].remote_calls == [("delete_atoms", ["a" * 32, "1"])]

    def test_delete_no_handles_is_noop(self, bridge_env):
        atom_bus = ScriptedAtomBus()
        runner = make_runner(atom_bus=atom_bus)
        runner.delete_atoms([])
        assert atom_bus.issued == []

    @pytest.mark.parametrize("handle", ["has space", "a" * 65, "", 123, "café!"])
    def test_delete_rejects_invalid_handles(self, bridge_env, handle):
        runner = make_runner()
        with pytest.raises(ValueError):
            runner.delete_atoms([handle])


class TestAnswerDecoder:
    def test_nested_handle_answer(self, bridge_env):
        make_runner()  # installs the decoder on the stubbed QueryAnswer
        answer = FakeQueryAnswer()
        answer.untokenize(nested_answer_token(TOP_HANDLE))
        assert answer.handles == [TOP_HANDLE]
        assert answer.assignment._mapping == {}
        assert answer.metta_expression == {}

    def test_flat_format_fallback(self, bridge_env):
        make_runner()
        answer = FakeQueryAnswer()
        answer.untokenize(f"1.0 0.5 1 {TOP_HANDLE} 0 0")
        assert answer.handles == [TOP_HANDLE]

    def test_garbage_rejected(self, bridge_env):
        make_runner()
        with pytest.raises(ValueError):
            FakeQueryAnswer().untokenize("garbage")

    def test_handle_bound_enforced(self, bridge_env):
        make_runner()
        # Flat-format fallback decodes, then the post-decode validation
        # rejects the oversized handle list.
        token = "1.0 0.5 " + str(5000) + " " + " ".join(["h"] * 5000) + " 0 0"
        with pytest.raises(ValueError):
            FakeQueryAnswer().untokenize(token)

    def test_metta_mappings_rejected(self, bridge_env):
        make_runner()
        # populate_metta_mapping is always disabled: a mapping in an answer
        # must be rejected, not decoded.
        with pytest.raises(ValueError):
            FakeQueryAnswer().untokenize(f"1.0 0.5 1 1 {TOP_HANDLE} 0 1 k v")


class TestModuleConstants:
    def test_delete_chunk_size_matches_cpp_client(self):
        # C++ AtomDBProxy::COMMAND_SIZE_LIMIT (AtomDBProxy.cc)
        assert DELETE_CHUNK_SIZE == 50

    def test_broker_command_names(self):
        assert write_client.ATOMDB_COMMAND == "atomdb"
        assert write_client.PATTERN_MATCHING_QUERY_COMMAND == "pattern_matching_query"
