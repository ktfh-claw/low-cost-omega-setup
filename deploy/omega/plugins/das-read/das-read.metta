!(import! &self (library Omega ./plugins/das-read/das_skills_read.py))

; das-read plugin (iteration 31, alignment lane): bind the das-retrieve skill
; clause to the mounted v2 adapter module so the DAS read path is a
; config-level artifact of this repo — the same remove-then-add
; single-definition invariant as the das-write plugin. On the deployed fork
; image the baked skills.metta clause routes to src/das_skills.py; this
; plugin replaces it with the plugin-mounted module, so both the clause and
; the implementation come from mounts. The src/das_skills.py :ro bind-mount
; in start.sh remains as a fallback while the fork image is the runtime.
; On a stock upstream image (none is published today) the skill must
; additionally be registered via add-skill — deferred until such an image
; exists.
; When OMEGA_DAS_ENABLED != 1 the plugin changes NOTHING: the stock clause
; stays in place and the module's own is_enabled gate double-blocks every
; call.

(= (loadOmegaPlugin)
   (if (py-call (das_skills_read.is_enabled))
       (progn
         (log INFO "das-read-plugin" "DAS read path bridged: das-retrieve routes to the mounted v2 adapter (metta/query mode)")
         (collapse (match &self (= (das-retrieve $body) $clause) (remove-atom &self (= (das-retrieve $body) $clause))))
         (add-atom &self (= (das-retrieve $body)
                            (py-call (das_skills_read.das_retrieve $body)))))
       (log INFO "das-read-plugin" "DAS read path not bridged (OMEGA_DAS_ENABLED != 1); stock behavior unchanged")))
