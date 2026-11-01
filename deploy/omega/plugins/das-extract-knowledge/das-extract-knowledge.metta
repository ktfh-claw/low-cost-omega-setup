; das-extract-knowledge plugin (2026-11-01, skill-split directive
; 2026-11-01 22:40 UTC). Extraction half of the skill split: registers a
; NEW skill carrying the generic knowledge-extraction procedure in its
; description (the surface the LLM sees: getSkills -> tool list).
;
; SKILL name: das-extract-knowledge (working name, kept).
;
; HANDLER: procedure-carrying — the LLM reads the description and
; follows the procedure. The handler clause binds to a Python module
; (das_extract_knowledge.py) that implements the checkpoint manifest
; writer (R3): when called with action="checkpoint", it appends the
; extracted predicates + receipts/handles + sources + timestamp to the
; checkpoint manifest in the Omega memory volume.
;
; When OMEGA_DAS_ENABLED != 1 the plugin changes NOTHING: the stock
; behavior is preserved as-is (the handler gates on the same config key
; as das-read; is_enabled() is the gate).

; Import the Python module that implements the checkpoint writer.
!(import! &self (library Omega ./plugins/das-extract-knowledge/das_extract_knowledge.py))

(= (loadOmegaPlugin)
   (if (py-call (das_extract_knowledge.is_enabled))
       (progn
         (log INFO "das-extract-knowledge-plugin" "Extraction skill registered (das-extract-knowledge)")
         ; Bind the handler clause: (das-extract-knowledge $body) routes to
         ; the Python module's handle() function. The handler is
         ; procedure-carrying: action="describe" returns the procedure
         ; text, action="checkpoint" writes the checkpoint manifest.
         (add-atom &self (= (das-extract-knowledge $body)
                            (py-call (das_extract_knowledge.handle $body))))
         ; Register the skill with the full WHY/WHEN/HOW description.
         ; The description carries the extraction procedure: generic
         ; procedure + constraints for extracting predicates from a text
         ; corpus into MeTTa predicate expressions, explicitly
         ; referencing the das-write skill (add-atom persistence path)
         ; and its receipt contract, and stating the bounded single-pass
         ; extraction constraint.
         (remove-skill das-extract-knowledge)
         (add-skill das-extract-knowledge "WHY: knowledge extraction builds a DAS knowledge base from a text corpus (files, websites, text bases) by deriving MeTTa predicate expressions (facts) and persisting them via the das-write skill (add-atom persistence path); a fact is justified ONLY by a BRIDGE-PERSIST-OK receipt, never by parametric memory or paraphrase. WHEN: call it whenever a task requires building a knowledge base from a text corpus — extract predicates from the corpus, persist them via the das-write skill (add-atom persistence path), and write a checkpoint manifest recording what was extracted. HOW: (1) read the corpus ONCE — each source file exactly once, no re-reading after processing; (2) derive predicate clauses (facts) from the text — keep the full stored arity and shape, ground arguments with quoted literals; (3) persist EACH ONE via: (metta \"(add-atom &persistent (<expression>) \\\"<source-url>\\\" (stv 0.9 0.8))\") — success is ONLY BRIDGE-PERSIST-OK: verified=<n> top=<handle>; (4) after EACH receipt, IMMEDIATELY append ONE line to the extraction record: expr <the-exact-expression> top=<handle> — the handle copied VERBATIM from the receipt's top= field; (5) write the checkpoint manifest (predicates + receipts/handles + sources + timestamp). Bounded single-pass: extract each fact once, record it, do not loop — never re-read a source file after processing it, never re-extract a fact already recorded." (json_body))
         (log INFO "das-extract-knowledge-plugin" "das-extract-knowledge skill description registered: extraction procedure + das-write receipt contract"))
       (log INFO "das-extract-knowledge-plugin" "das-extract-knowledge skill not registered (OMEGA_DAS_ENABLED != 1)")))
