; das-grounded-reasoning plugin (2026-11-01, skill-split directive
; 2026-11-01 22:40 UTC). Reasoning half of the skill split: registers a
; NEW skill carrying the generic grounded-reasoning procedure in its
; description (the surface the LLM sees: getSkills -> tool list).
;
; SKILL name: das-grounded-reasoning (working name, kept).
;
; HANDLER: procedure-carrying — the LLM reads the description and
; follows the procedure. The handler clause binds to a Python module
; (das_grounded_reasoning.py) that implements the checkpoint manifest
; reader (R3): when called with action="read_checkpoint", it returns
; the latest checkpoint manifest (predicates verbatim) as the reasoning
; entry point.
;
; When OMEGA_DAS_ENABLED != 1 the plugin changes NOTHING: the stock
; behavior is preserved as-is (the handler gates on the same config key
; as das-read; is_enabled() is the gate).

; Import the Python module that implements the checkpoint reader.
!(import! &self (library Omega ./plugins/das-grounded-reasoning/das_grounded_reasoning.py))

(= (loadOmegaPlugin)
   (if (py-call (das_grounded_reasoning.is_enabled))
       (progn
         (log INFO "das-grounded-reasoning-plugin" "Reasoning skill registered (das-grounded-reasoning)")
         ; Bind the handler clause: (das-grounded-reasoning $body) routes
         ; to the Python module's handle() function. The handler is
         ; procedure-carrying: action="describe" returns the procedure
         ; text, action="read_checkpoint" reads the checkpoint manifest.
         (add-atom &self (= (das-grounded-reasoning $body)
                            (py-call (das_grounded_reasoning.handle $body))))
         ; Register the skill with the full WHY/WHEN/HOW description.
         ; The description carries the reasoning procedure: generic
         ; procedure + constraints for answering questions strictly from
         ; the DAS knowledge base, explicitly referencing the das-write
         ; skill (add-atom persistence path) and its receipt contract.
         (remove-skill das-grounded-reasoning)
         (add-skill das-grounded-reasoning "WHY: grounded reasoning answers questions strictly from the DAS knowledge base; an answer is justified ONLY by das-retrieve evidence, never by parametric memory. WHEN: call it whenever a question must be answered from stored knowledge — formalize the question into MeTTa, retrieve from DAS, execute the reasoning, answer strictly from the stored facts. HOW: (1) read the checkpoint manifest (the phase boundary between extraction and reasoning — it records which predicates exist, verbatim, for query reuse); (2) formalize the question as one MeTTa clause — ground one side with a quoted literal, bind the target with a $variable, keep the stored arity/shape and direction; (3) retrieve from DAS via das-retrieve — quote the real tool output; count=0 means absent OR wrongly-shaped (before concluding absence, re-probe once with the complementary direction and once with the exact spelling from your extraction record); (4) execute the reasoning with the metta skill — NAL/PLN operators are STRICTLY 2-ARGUMENT; (5) answer strictly from the DAS KB — never invent content, never fabricate handles." (json_body))
         (log INFO "das-grounded-reasoning-plugin" "das-grounded-reasoning skill description registered: reasoning procedure + das-retrieve grammar"))
       (log INFO "das-grounded-reasoning-plugin" "das-grounded-reasoning skill not registered (OMEGA_DAS_ENABLED != 1)")))
