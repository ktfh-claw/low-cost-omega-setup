; pin-memory plugin (2026-10-23, windowless-room v3 lane).
;
; WHY THIS PLUGIN EXISTS (live evidence, wr3-20261023 run): the stock pin
; skill in the baked skills.metta is a NO-OP STUB —
;     (= (pin $x) PIN-SUCCESS)
; — it discards the item. Its registered description promises short-term
; working memory ("keep track of task state and relevant query results as
; query returns are only available once and gone next cycle"), but nothing
; is stored, so the promise is false and agents that rely on it lose their
; working state every cycle. In the live benchmark run the agent pinned
; items and lost them, contributing to a re-ingest churn loop.
;
; THE FIX (by design, no new mechanism invented): rebind pin to the agent's
; OWN prompt-extension path — (add-prompt-extension $handle $text) adds an
; atom that getPromptExtensions joins into EVERY following LLM prompt in
; this container. So a pinned item becomes a visible working-memory section
; for all subsequent cycles. The handle is the text itself (stable, so
; pinning the same text twice is a dedup no-op; remove-prompt-extension can
; un-pin by handle). Single-definition invariant: the stock clause is
; removed first, then the bridged clause is installed.
;
; Persistence scope: &self atoms live for the container lifetime — pinned
; items survive wake cycles within one agent run, and are (by design) NOT
; durable across container restarts. Durable memory is DAS + memory-volume
; files. The skill description is re-registered to state these semantics
; truthfully.

(= (loadOmegaPlugin)
   (progn
     (log INFO "pin-plugin" "pin rebound: pinned items become prompt extensions (cross-cycle working memory)")
     (collapse (match &self (= (pin $x) $clause) (remove-atom &self (= (pin $x) $clause))))
     (add-atom &self (= (pin $x)
        (progn
          (add-prompt-extension $x $x)
          PIN-SUCCESS)))
     (remove-skill pin)
     (add-skill pin "Pin a string as working memory: the item is added as a prompt extension and re-appears in EVERY following prompt of this run (until the run restarts) — pin task state, key facts, receipts, and query results you must not lose between cycles. Pinning the same text twice is a no-op. Not durable across restarts: for that, write a memory file or persist to DAS." (message))
     (log INFO "pin-plugin" "pin skill description re-registered (working-memory semantics)")))
