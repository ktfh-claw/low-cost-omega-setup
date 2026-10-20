# Issue draft 1 — Query Engine crashes on mis-routed ATOMDB command (uncaught exception)

**Target:** singnet/das · **Severity: HIGH** · **Type:** bug
**Status:** DRAFT — re-validated against upstream `48507929` (2026-10-20); filing upstream requires Balázs's explicit go-ahead.

## Defect

In a multi-peer DAS service-bus deployment, routing an `atomdb` command to a query-engine node crashes the query engine with an uncaught exception instead of returning an error or forwarding the command:

```
std::runtime_error("Processor is not registered to process command: atomdb")
```

Re-validation 2026-10-20 (upstream master `48507929`): the throw is still exactly where it was — `src/service_bus/ServiceBus.cc:172`, `RAISE_ERROR("Processor is not registered to process command: " + this->command)` — and `RAISE_ERROR` (`src/commons/Utils.h:202`) expands to `Utils::error(msg, true, false)` = fatal process exit with stack trace. Defect confirmed unchanged.

The QE process exits (container crash-restarts under Docker restart policy). Related gap: command-ownership discovery does not propagate to late-joining bus peers — a client that joins a different bus peer (e.g. the query-engine's) cannot have its `atomdb` commands routed to the atomdb-broker; it must join the broker directly.

## Repro (live-verified 2026-10-18, production-identical stack)

1. Deploy the standard multi-container stack (mongodb, redis, attention-broker, query-engine, atomdb-broker) with the python client joining the service bus.
2. Configure the client's callback-peer rewrite host to point at the query-engine instead of the atomdb-broker.
3. Issue any `AtomDBProxy.add_atoms(...)` call.
4. Observed: QE container exits with the uncaught `std::runtime_error`; docker restarts it. Client gets no usable error.
5. Expected: the QE either forwards the command to the owning peer or replies with a structured error; it must not crash the process.

## Evidence

- Live reproduction log: re-eval campaign state file tick 2 (`memory/omega-das-integration-reeval/state.md`).
- Crash line: `Processor is not registered to process command: atomdb`.
- Deployment invariants documented in bridge repo `docs/architecture.md` §5 (broker binds 0.0.0.0; clients join the broker directly; callback rewrite host = broker name).

## Proposed fix (for the later robustness PR; semantics to be agreed with maintainers)

Register an explicit fallback handler for unowned/unroutable commands in the bus message loop: forward when an owner is known, otherwise reply with an error message on the bus instead of throwing.
