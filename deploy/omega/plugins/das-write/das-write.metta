!(import! &self (library Omega ./plugins/das-write/das_write_bridge.py))

; das-write plugin (iterations 11 + 21, omega-das-bridge campaign):
; rebind the `metta` skill clause so that (add-atom &persistent ...) routes
; to the write-bridge facade for durable, verified DAS writes instead of
; the stock Prolog-space assert (which is container-lifetime only). The
; stock clause is removed first and a bridged clause installed in its
; place: a second (= (metta ...) ...) clause added alongside the stock one
; would DOUBLE-evaluate (both clauses fire on every call), so the remove-
; then-add single-definition invariant is load-bearing. When
; dasWriteEnabled != 1 (stock config key: command line, config.yaml,
; or OMEGA_dasWriteEnabled environment) the plugin changes NOTHING: the stock
; clause stays in place and local PeTTa persistence behavior is
; preserved as-is.
;
; v2 (2026-10-21, provenance campaign) additionally binds the
; `archive-source` skill clause: (archive-source "https://...") fetches
; the URL at research time and archives its content into the git
; provenance repo through the facade, returning the commit hash the agent
; attaches to every fact derived from that source via the v2 add-atom
; provenance suffix:
;   (add-atom &persistent (Fact ...) "https://source" "git:<sha>" (stv 0.9 0.8))

(= (loadOmegaPlugin)
   (if (py-call (das_write_bridge.is_enabled))
       (progn
         (log INFO "das-write-plugin" "DAS persistent-space bridging enabled: (add-atom &persistent ...) routes to the write-bridge; (archive-source ...) captures URL sources into the provenance git repo")
         (collapse (match &self (= (metta $str) $body) (remove-atom &self (= (metta $str) $body))))
         (add-atom &self (= (metta $str)
              (let $bridged (py-call (das_write_bridge.intercept $str))
                   (if (== $bridged ())
                        (let $code (sread $str)
                             (repr (swrite (eval $code))))
                        (car-atom $bridged)))))
         (add-atom &self (= (archive-source $url)
              (py-call (das_write_bridge.archive_source $url)))))
       (log INFO "das-write-plugin" "DAS persistent-space bridging disabled")))
