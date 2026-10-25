; metta-grammar plugin (windowless-room scenario A close-out, 2026-10-25):
; re-register the metta skill with a WHY/WHEN/grammar description — the
; stock registration in skills.metta:153 is one sentence ("Evaluate a
; MeTTa s-expression...") and documents neither the NAL/PLN 2-argument
; contract nor the ephemeral-atomspace chaining rule. Live evidence
; (scenario A, 2026-10-24/25): the agent made ~321 metta calls, almost all
; 3+-argument (|~ a b c ...) forms that can NEVER match the strictly
; 2-argument operator definitions (lib_pln.metta:306, lib_nal.metta:110),
; returning (partial ...)/() — while byte-exact 2-arg tutorial forms
; executed live with correct stv math. Same defect class as pre-v3
; das-retrieve: the skill description is the surface the LLM sees, so the
; operator contract belongs HERE. Only the skill listing is re-registered
; (remove-skill + add-skill, single-definition invariant); the stock
; handler clause (= (metta $str) ...) in skills.metta is correct and
; untouched. Examples deliberately use upstream tutorial vocabulary
; (garfield/animal, pingu/bird), never benchmark vocabulary.

(= (loadOmegaPlugin)
   (progn
     (log INFO "metta-grammar-plugin" "Upgrading metta skill description: NAL/PLN 2-arg contract")
     (remove-skill metta)
     (add-skill metta "WHY: this skill evaluates MeTTa through the live interpreter — a reasoning step is justified ONLY by an executed interpreter result with its (stv ...) truth value, never by prose you compose yourself. WHEN: whenever a task requires formal, logical, or neurosymbolic reasoning over known facts (derivation, deduction, modus ponens, similarity), and to evaluate any MeTTa expression programmatically. HOW: pass ONE s-expression (omit the leading !). NAL/PLN reasoning operators are STRICTLY 2-ARGUMENT: (|- premiseA premiseB) is NAL and (|~ premiseA premiseB) is PLN; each premise is an (expression (stv strength confidence)) pair, and a successful call returns ((derived-expression (stv s c))). NAL works on (--> subject object) atoms, e.g. (|- ((--> garfield animal) (stv 1.0 0.9)) ((--> garfield mammal) (stv 1.0 0.9))) derives a third (--> ...) atom. PLN matches patterns over Inheritance/Implication/Evaluation/Member atoms, e.g. (|~ ((Implication (Inheritance $x feathered) (Inheritance $x bird)) (stv 1.0 0.9)) ((Inheritance pingu feathered) (stv 1.0 0.9))) derives ((Inheritance pingu bird) (stv 1.0 0.81)). Three or more premises in ONE call NEVER evaluate — the atomspace is EPHEMERAL between calls, so chain multi-step reasoning by feeding the derived output of one call in as a premise of the next call. Quote interpreter output verbatim including (stv ...) as your evidence. Tool results are gone next cycle: immediately pin or write-file every successful derivation you must keep. On syntax_error read the offending form, fix the shape (almost always argument count or arity), retry once; never retry more than twice." (sexpression))
     (log INFO "metta-grammar-plugin" "metta skill description upgraded: why/when/grammar contract registered")))
