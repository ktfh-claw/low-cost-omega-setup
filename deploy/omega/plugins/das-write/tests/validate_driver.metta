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

; PROBE-1: bridged &persistent write.
; Expect: BRIDGE-PERSIST-OK: verified=3 handles=<h1,h2,h3>  (when enabled)
;         stock PeTTa result, no BRIDGE status              (when disabled)
!(metta "(add-atom &persistent (Inheritance (Concept \"omega-das-write-hook-canary-20261020-iter11\") (Concept \"das-write-hook-test\")))")

; PROBE-2: stock fall-through sanity for a non-target form. Expect: 42
!(metta "(* 6 7)")

; PROBE-3: remove-atom interception. Expect: BRIDGE-PERSIST-REMOVE-UNSUPPORTED: ...
!(metta "(remove-atom &persistent (Concept \"x\"))")

; PROBE-4: the gate value as the plugin itself resolves it (stock config
; machinery: command line > env > config.yaml). Expect: True when enabled.
!(py-call (das_write_bridge.is_enabled))
