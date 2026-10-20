!(import! &self (library Omega ./plugins/das-write/das_write_bridge.py))

; das-write plugin (iteration 11, omega-das-bridge campaign, Phase 2):
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

(= (loadOmegaPlugin)
   (if (py-call (das_write_bridge.is_enabled))
       (progn
         (log INFO "das-write-plugin" "DAS persistent-space bridging enabled: (add-atom &persistent ...) routes to the write-bridge")
         (collapse (match &self (= (metta $str) $body) (remove-atom &self (= (metta $str) $body))))
         (add-atom &self (= (metta $str)
              (let $bridged (py-call (das_write_bridge.intercept $str))
                   (if (== $bridged ())
                        (let $code (sread $str)
                             (repr (swrite (eval $code))))
                        (car-atom $bridged))))))
       (log INFO "das-write-plugin" "DAS persistent-space bridging disabled")))
