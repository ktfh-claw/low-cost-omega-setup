; validate_driver.metta — metta-grammar plugin test-container driver (2026-10-25,
; windowless-room scenario A close-out).
;
; Enabled run (from deploy/omega/plugins/metta-grammar):
;   IMAGE=omegaclaw:das-a44739e tests/run_driver.sh /tmp/metta-grammar.log
;   (IMAGE defaults to the live agent's tag so validation matches the
;   runtime that will load the plugin)
;
; Mirrors run.metta's bootstrap minus the agent loop/channels/memory (same
; minimal faithful path as the das-read driver): initConfig -> initLogger ->
; initPlugins loads ALL FOUR plugins exactly as the live agent does. The DAS
; plugins stay inert without OMEGA_DAS_* env — this validation covers only
; the metta skill re-registration and the handler path.

!(import! &self (library lib_import))
!(git-import! "https://github.com/singnet/Omega.git")
!(import! &self (library Omega lib_omega))

!(initConfig)
!(initLogger)
!(initPlugins)

; PROBE-1: getSkills must print exactly ONE metta entry whose description
; starts with "WHY: this skill evaluates MeTTa" and carries the
; STRICTLY-2-ARGUMENT NAL/PLN contract plus the ephemeral-atomspace
; chaining rule. The stock one-line registration ("Evaluate a MeTTa
; s-expression, since its a s-expression omit the ! in the beginning...")
; must NOT appear. A duplicated entry means remove-skill + add-skill did
; not hold the single-definition invariant.
!(getSkills)

; PROBE-2: single-definition check — a second getSkills must show the
; identical single metta entry (das-read precedent: a duplicated clause
; would print twice).
!(getSkills)

; PROBE-3: the stock handler clause (= (metta $str) ...) must be intact —
; a strictly 2-argument NAL form through the metta skill must execute live
; and derive a real stv conclusion. Expected (tutorial/live-verified):
; ((--> (× sam animal) friend) (stv 1.0 0.44751381215469616))
!(metta "(|- ((--> (× sam garfield) friend) (stv 1.0 0.9)) ((--> garfield animal) (stv 1.0 0.9)))")

; PROBE-4: a 3-argument form must NOT match the 2-arg operators — expected
; (partial ...) or () unevaluated output, documenting the never-match
; contract the upgraded description warns about (scenario-A live evidence:
; the agent's 3+-arg forms all fell into this trap).
!(metta "(|- ((--> sam garfield) (stv 1.0 0.9)) ((--> garfield animal) (stv 1.0 0.9)) ((--> sam animal) friend))")
