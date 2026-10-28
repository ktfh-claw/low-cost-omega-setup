; validate_driver.metta — das-write plugin test-container driver (iteration 11+).
;
; Loaded directly by main.pl:
;   sh run.sh /PeTTa/validate_driver.metta dasWriteEnabled=1 \
;     dasWriteOrigin=http://write-bridge:8080 commchannel=test provider=Test
; (working_dir = /PeTTa because the file is mounted at /PeTTa/ — library
; resolution then matches the stock run.metta bootstrap exactly).
;
; Mirrors run.metta's bootstrap and the (omega) init prefix, minus the
; agent loop, channels, and memory stack (no embeddings, no chroma, no
; LLM): initConfig -> initLogger -> initPlugins is the minimal faithful
; path that loads the das-write plugin the same way the live agent does.
; Top-level bare forms are DATA in MeTTa file loading — only !-prefixed
; forms are evaluated. Every probe below is a directive whose result is
; printed by main.pl — one line per probe, deterministic, container exits
; after the last form.

!(import! &self (library lib_import))
!(git-import! "https://github.com/singnet/Omega.git")
!(import! &self (library Omega lib_omega))

!(initConfig)
!(initLogger)
!(initPlugins)

; PROBE-1: bridged &persistent write (v1, suffix-less). With a DEAD
; dasWriteOrigin (no facade contact, zero residue) the expectation is:
;         BRIDGE-PERSIST-WRITE-FAILED: request failed   (when enabled)
;         stock PeTTa result, no BRIDGE status             (when disabled)
; Against the v4 facade (Phase 7 deploy) it becomes
;         BRIDGE-PERSIST-OK: verified=<n> top=<handle>
!(metta "(add-atom &persistent (Inheritance (Concept \"omega-das-write-hook-canary-20261020-iter11\") (Concept \"das-write-hook-test\")))")

; PROBE-5: v3 source-ref grammar through the live clause — the ref URL is
; unreachable by construction, so the resolver fails BEFORE any facade POST:
; Expect: BRIDGE-PERSIST-WRITE-FAILED: source fetch failed (...)  (enabled)
!(metta "(add-atom &persistent (Concept \"probe5-v3-dead-ref\") \"http://127.0.0.1:9/dead.md\")")

; PROBE-6: retired v2 git-citation shape rejected with the actionable status:
; Expect: BRIDGE-PERSIST-WRITE-FAILED: git citations are no longer accepted ...
!(metta "(add-atom &persistent (Concept \"probe6-v2-rejected\") \"https://example.com/x\" \"git:cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd\")")

; PROBE-2: stock fall-through sanity for a non-target form. Expect: 42
!(metta "(* 6 7)")

; PROBE-3: remove-atom interception. Expect: BRIDGE-PERSIST-REMOVE-UNSUPPORTED: ...
!(metta "(remove-atom &persistent (Concept \"x\"))")

; PROBE-4: the gate value as the plugin itself resolves it (stock config
; machinery: command line > env > config.yaml). Expect: True when enabled.
!(py-call (das_write_bridge.is_enabled))
