!(import! &self (library Omega ./plugins/das-write/das_write_bridge.py))

; das-write plugin (iterations 11 + 21 + v4 transparent-provenance campaign):
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
; v3 (2026-10-28, transparent-provenance campaign): provenance is fully
; transparent to the agent. The add-atom form is
;   (add-atom &persistent <expr> "<http(s)-url | abs-container-path>" [(stv s c)])
; — the agent passes ONLY the source reference; the plugin fetches or
; reads the source, hashes it (sha256), appends (ref, sha256) to the git
; source ledger via the facade, and performs the gated DAS write. The
; receipt is
;   BRIDGE-PERSIST-OK: verified=<n> top=<handle> [stv=(s,c)]
; — top=<handle> is the fact's top-link atom handle. There is no
; capture skill and no agent-side git citation: archiving is
; automatic inside this single skill call.

(= (loadOmegaPlugin)
   (if (py-call (das_write_bridge.is_enabled))
       (progn
         (log INFO "das-write-plugin" "DAS persistent-space bridging enabled: (add-atom &persistent <expr> <http(s)-url | abs-container-path> [(stv s c)]) routes to the write-bridge with transparent provenance; receipt: BRIDGE-PERSIST-OK: verified=<n> top=<handle>")
         (collapse (match &self (= (metta $str) $body) (remove-atom &self (= (metta $str) $body))))
         (add-atom &self (= (metta $str)
              (let $bridged (py-call (das_write_bridge.intercept $str))
                   (if (== $bridged ())
                        (let $code (sread $str)
                             (repr (swrite (eval $code))))
                        (car-atom $bridged))))))
       (log INFO "das-write-plugin" "DAS persistent-space bridging disabled")))
