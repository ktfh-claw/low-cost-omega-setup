; validate_driver.metta — das-read plugin test-container driver (iteration 31;
; v3 upgrade probe 2026-10-23).
;
; Enabled run (from deploy/omega/plugins/das-read):
;   IMAGE=omegaclaw:das-a44739e sh tests/run_driver.sh /tmp/dasread-enabled.log
;   (IMAGE defaults to the live agent's tag so the validation matches the
;   runtime that will load the plugin)
; Disabled run: DASREAD_MODE=disabled ...
;
; Mirrors run.metta's bootstrap minus the agent loop/channels/memory (same
; minimal faithful path as the das-write driver): initConfig -> initLogger ->
; initPlugins loads both plugins exactly as the live agent does.

!(import! &self (library lib_import))
!(git-import! "https://github.com/singnet/Omega.git")
!(import! &self (library Omega lib_omega))

!(initConfig)
!(initLogger)
!(initPlugins)

; PROBE-1: das-retrieve through the plugin-bound clause (metta mode; a
; two-variable pattern keeps escaping at one level). Enabled run expects:
; DAS_RETRIEVE_OK untrusted=true count=3 truncated=false results=[...]
; Disabled run expects: DAS_RETRIEVE_FAILED: adapter is disabled
!(das-retrieve "{\"metta\": \"(Inheritance $X $Y)\", \"max_answers\": 3}")

; PROBE-2: repeat — single-definition check (a duplicated clause would
; superpose and print TWO results). Enabled expects the identical single line.
!(das-retrieve "{\"metta\": \"(Inheritance $X $Y)\", \"max_answers\": 3}")

; PROBE-3: failing shape must surface the proxy error verbatim (v2 fix).
; Enabled expects: DAS_RETRIEVE_FAILED: proxy returned HTTP 400: structural
; queries must start with LINK_TEMPLATE; use the metta field for MeTTa-form
; queries
!(das-retrieve "{\"tokens\": [\"decentralized\", \"AI\"], \"max_answers\": 10}")

; PROBE-4 (v3, 2026-10-23): the plugin must ALSO re-register the das-retrieve
; dynamic-skill atom with the upgraded description (why/when/grammar
; contract). getSkills prints every registered skill tuple; the enabled log
; must contain exactly ONE das-retrieve entry (remove-skill + add-skill
; single-definition invariant) and its description must start with
; "WHY: DAS is your persistent knowledge store" and carry the
; WHEN/HOW/grammar clauses. A duplicated entry or the stock one-line
; "Retrieve bounded read-only DAS answers as untrusted data." registration
; means the upgrade did NOT take.
!(getSkills)

; PROBE-5 (v3, 2026-10-23): the pin plugin must rebind the no-op stock pin
; stub to the prompt-extension path: pin an item, then print the prompt
; extensions — the pinned text MUST appear among them. Expects
; PIN-SUCCESS then a getPromptExtensions line containing BENCH-PIN-TEST.
!(pin "BENCH-PIN-TEST")
!(getPromptExtensions)

; PROBE-6: single-definition check for pin — pinning the same text twice
; must be a dedup no-op (add-prompt-extension with the same handle replaces
; the atom), so the extensions still contain exactly ONE BENCH-PIN-TEST.
!(pin "BENCH-PIN-TEST")
!(getPromptExtensions)
