# kube-loop

A minimal demo of an **AI coding agent that closes the SDLC loop** on Kubernetes: write code → deploy → execute → observe telemetry → reason → iterate.

## What it does

An AI coding agent is given a software development task. It writes the code, deploys it to a Kubernetes cluster, exercises it, observes the resulting behavior through telemetry, and uses what it learns to drive the next iteration — closing the build-observe-iterate loop autonomously.


## Stack

| Layer | Component |
|---|---|
| Cluster runtime | Colima + k3s (local Kubernetes on macOS) |
| Coding agent | OpenHands SDK (Python) |
| Telemetry | OpenLIT (OTLP traces + ClickHouse store) |
| Workload | FastAPI app deployed as a Kubernetes Deployment + NodePort Service |


## Architecture

```
┌─────────────────────────────┐      ┌──────────────────────────────┐
│  Local Mac (Python venv)    │      │   Colima VM (k3s cluster)    │
│                             │      │                              │
│  • OpenHands agent          │      │  default namespace           │
│  • demo_loop.py             │◄────►│   • demo-api Deployment      │
│  • kubectl, docker CLIs     │      │   • demo-api NodePort:30080  │
│  • port-forwards            │      │                              │
│    (3000 UI, 4318 OTLP)     │      │  openlit namespace           │
│                             │─────►│   • OTLP collector           │
│                             │      │   • UI + ClickHouse          │
└─────────────────────────────┘      └──────────────────────────────┘
            │
            ▼
       LLM API (OpenAI / Anthropic)
```

## Quick start

```bash
# 1. Prerequisites
brew install colima docker kubectl helm node@20 python@3.12

# 2. Start cluster
colima start --cpu 4 --memory 10 --disk 60 --kubernetes --network-address

# 3. Install OpenLIT
helm repo add openlit https://openlit.github.io/helm/
helm install openlit openlit/openlit --namespace openlit --create-namespace
kubectl port-forward svc/openlit 3000:3000 -n openlit &
kubectl port-forward svc/openlit 4318:4318 -n openlit &

# 4. Set up the agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install openhands-sdk openhands-tools openlit

# 5. Configure
export LLM_API_KEY=...
export LLM_MODEL=anthropic/claude-sonnet-4-6
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export COLIMA_IP=$(colima list | awk 'NR==2 {print $8}')

# 6. Run the loop
python demo_loop.py
```

After it completes:
- API is live at `http://$COLIMA_IP:30080/health`
- Agent's analysis is in `/tmp/demo-api/analysis.md`
- Traces are at `http://localhost:3000` (login: `user@openlit.io` / `openlituser`)

## The loop

`demo_loop.py` runs two iterations:

1. **Build & deploy** — agent writes the FastAPI app, Dockerfile, and k8s manifest; builds the image; applies the manifest; calls the API; records results to `results.json`.
2. **Analyze & plan** — agent reads `results.json` and pod logs, verifies behavior, and writes `analysis.md` with proposed improvements for the next iteration.

To extend to N iterations, feed each iteration's `analysis.md` as context into the next prompt.

## Why this exists

Most AI coding agents stop at "writes code." Closing the loop — deploying, observing, and reasoning over telemetry — is where the interesting capability gaps appear. This repo is a minimal substrate for experimenting with that loop on a local machine, without the operational overhead of a full agent platform.

## Project structure

```
.
├── README.md
├── demo_loop.py           # Main orchestrator
├── test_agent.py          # Hello-world agent smoke test
└── docs/
    └── setup-path-c.md    # Full setup guide
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `curl $COLIMA_IP:30080` times out | Use `kubectl port-forward svc/demo-api 8090:8080` instead |
| Pod stuck in `ImagePullBackOff` | Confirm `imagePullPolicy: IfNotPresent` and that `docker images` shows `demo-api:latest` |
| `KeyError: 'TerminalTool'` | `register_tool(...)` calls must run before `Agent(...)` |
| No traces in OpenLIT | Verify port-forward on 4318: `lsof -i :4318` |
| Colima IP changed after restart | Re-export `COLIMA_IP` from `colima list` |

## License

MIT

