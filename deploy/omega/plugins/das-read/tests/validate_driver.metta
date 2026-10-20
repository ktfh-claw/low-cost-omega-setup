; validate_driver.metta — das-read plugin test-container driver (iteration 31).
;
; Enabled run (from deploy/omega/plugins/das-read):
;   sh tests/run_driver.sh /tmp/dasread-enabled.log -e OMEGA_DAS_ENABLED=1 \
;     -e OMEGA_DAS_PROXY_ORIGIN=http://read-proxy:8080
; Disabled run: omit the -e OMEGA_DAS_ENABLED flag.
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
