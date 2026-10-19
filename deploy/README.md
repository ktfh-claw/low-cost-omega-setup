# deploy/ — validated deployment set (imported from the live OVH host)

Imported verbatim on **2026-10-19** from the running validated deployment on `omega-experimental` (`139.99.208.186` / Tailscale `100.84.81.96`). These are the exact files the live lane uses — the bridge runbook (`docs/runbook.md`) assembles them for a from-scratch reproduction. Secrets are **not** stored here: every credential arrives via environment files created by the operator from the `*.example` templates.

## Layout

```
deploy/
├── omega/                                   # the Omega agent container
│   ├── config-overlay.yaml                  # FULL Omega config overlay (the one we've been using)
│   ├── omega-curiosity.service              # systemd unit (start/stop/restart policy, docker gate)
│   ├── start.sh                             # container create/connect/attach glue (image omegaclaw:das-f38217f)
│   └── runtime.env.example                  # env-file template — key names only, values are secrets
└── das/                                     # the DAS side (compose project "omega-das-integration")
    ├── compose.yaml                         # mongodb, redis, attention-broker, query-engine, read-proxy (+ operator-profile services)
    ├── .env.example                         # pinned image digests + Mongo credentials (digest-pinning policy: tags rejected)
    ├── config/config.json.template          # rendered by scripts/render-config.sh → generated/config.json
    ├── proxy/                               # bounded read proxy (app.py, das_client.py, Dockerfile)
    └── scripts/                             # preflight, render-config, up, rollback, backup-volumes
```

## Omega config overlay (`deploy/omega/config-overlay.yaml`)

This is the complete overlay mounted read-only into the container at `/PeTTa/repos/Omega/config/config.yaml` (see `start.sh`). Notable settings of the running campaign:

- `commchannel: telegram` + `telegramAutonomousWake` (overridden on the container command line), `provider: Anthropic` in the file with `provider=ASIOne model=asi1-ultra` passed at container start (command line wins).
- `embeddingprovider: Local`; memory at `./repos/Omega/memory`; `securityPolicyPath: ./repos/Omega/profile/policy.yaml`; `memoryExportEnabled: false`.
- Loop budget: `maxNewInputLoops: 50`, `maxWakeLoops: 10`, `wakeupInterval: 180`, `maxOutputToken: 6000`, `reasoningMode: medium`.
- OpenClaw plugin: `openClawEnabled: disabled`, `openClawURL: http://172.17.0.1:18789` (fallback only; real Gateway target injected via Nginx proxy, agent never sees the token).

## What is deliberately NOT here

- `runtime.env` real values (API keys, bot token, auth secrets) — operator-created from `runtime.env.example`.
- `das/.env` real values (image digests, Mongo credentials) — from `.env.example`.
- `scripts/campaign_import.py` and the pre-bridge operator-import README — retired lane; preserved as `historical/das-deploy-readme-20261005.md` (the import tooling itself lives in `ktfh-claw/das-toolbox` history; its replacement wrapper is Phase 2 of the campaign plan).
- Generated artifacts (`generated/config.json`, `__pycache__`) — produced by `scripts/render-config.sh`.

## Provenance notes

- `config-overlay.yaml` matches the live file at `/home/ubuntu/omega-curiosity/config-overlay.yaml` (mtime 2026-10-17, the asi1-ultra cutover). On OVH, `.bak-*` siblings preserve earlier variants; they are not imported.
- `start.sh` hard-codes image `omegaclaw:das-f38217f` (OmegaClaw-Core fork line). The compose DAS images are pinned by sha256 digest via `.env`.
- The systemd unit and `start.sh` together implement the stop/restart policy used for the current pause (service disabled; container removed).
