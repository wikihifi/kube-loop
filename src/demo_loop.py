"""
demo_loop.py — Closed-loop SDLC demo

Runs N iterations where each one:
  1. Reads the previous iteration's pod logs and OTEL telemetry
  2. Decides ONE concrete improvement based on what it observed
  3. Modifies the code, rebuilds, and redeploys with a new version tag
  4. Calls all endpoints and records what changed and why

After the loop, you can:
  - Diff /tmp/demo-api/main.py.v1 vs main.py.v2 vs main.py.v3 to see code evolution
  - Read /tmp/demo-api/iteration_N_why.md to see what telemetry drove each change
  - Curl /version on the live service to see the iteration counter advance
"""

import os
import sys
import json
import subprocess
import time
from pathlib import Path

import openlit
from openhands.sdk import LLM, Agent, Conversation
from openhands.sdk.tool import Tool, register_tool
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

# ----- Tool registration -----
register_tool("TerminalTool", TerminalTool)
register_tool("FileEditorTool", FileEditorTool)

# ----- Telemetry init -----
openlit.init(
    otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
)

# ----- Config -----
NUM_ITERATIONS = int(os.getenv("NUM_ITERATIONS", "3"))
WORK_DIR = "/tmp/demo-api"
LLM_MODEL = os.getenv("LLM_MODEL")
LLM_API_KEY = os.getenv("LLM_API_KEY")

if not LLM_API_KEY or not LLM_MODEL:
    sys.exit("ERROR: LLM_API_KEY and LLM_MODEL env vars are required")

llm = LLM(model=LLM_MODEL, api_key=LLM_API_KEY)

# Ensure workspace exists
Path(WORK_DIR).mkdir(parents=True, exist_ok=True)


# ============================================================
# Helpers — gather signals for the next iteration
# ============================================================

def get_pod_logs() -> str:
    """Grab the last 40 lines of demo-api pod logs."""
    try:
        result = subprocess.run(
            ["kubectl", "logs", "-l", "app=demo-api", "--tail=40", "--all-containers=true"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "(no logs yet)"
    except Exception as e:
        return f"(could not fetch logs: {e})"


def get_pod_status() -> str:
    """Get the current pod status — running, restart count, etc."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "pods", "-l", "app=demo-api",
             "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount,IMAGE:.spec.containers[0].image"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "(no pods yet)"
    except Exception as e:
        return f"(could not fetch status: {e})"


def get_recent_endpoint_calls() -> str:
    """
    Summary of what endpoints the agent last called.
    In a fuller version this would query OpenLIT's API; for now we read
    the prior iteration's results.json which the agent records itself.
    """
    prior = Path(WORK_DIR) / "last_results.json"
    if not prior.exists():
        return "(no prior endpoint call data)"
    try:
        return prior.read_text()[:2000]
    except Exception:
        return "(could not read prior results)"


def read_prior_why(iteration_n: int) -> str:
    """Read the why-file from the previous iteration so the agent has continuity."""
    if iteration_n <= 1:
        return "(this is the first iteration — no prior history)"
    prior = Path(WORK_DIR) / f"iteration_{iteration_n - 1}_why.md"
    if prior.exists():
        return prior.read_text()
    return "(no prior why-file)"


# ============================================================
# Prompts
# ============================================================

ITERATION_1_PROMPT = """
You are starting iteration 1 of a closed-loop SDLC demo. There is no prior state.

Build the v1 baseline FastAPI service and deploy it to Kubernetes.

DO THESE STEPS IN ORDER, confirming each before moving to the next:

1. Create /tmp/demo-api/main.py — FastAPI app with EXACTLY these endpoints:
   - GET /health   -> {"status": "ok"}
   - GET /version  -> {"version": "v1", "iteration": 1, "improvements_since_v1": []}
   - GET /data     -> {"items": [1, 2, 3], "count": 3}

   IMPORTANT: Use plain print() for logging (no structured logging yet —
   that's deliberately left as an improvement opportunity for later iterations).

2. Save a snapshot: cp /tmp/demo-api/main.py /tmp/demo-api/main.py.v1

3. Create /tmp/demo-api/requirements.txt:
   fastapi
   uvicorn

4. Create /tmp/demo-api/Dockerfile:
   FROM python:3.12-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY main.py .
   EXPOSE 8080
   CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

5. Create /tmp/demo-api/k8s.yaml with a Deployment + NodePort Service:
   - image: demo-api:v1
   - imagePullPolicy: IfNotPresent
   - container port 8080, NodePort 30080
   - labels app=demo-api

6. Build: docker build -t demo-api:v1 /tmp/demo-api/

7. Apply: kubectl apply -f /tmp/demo-api/k8s.yaml

8. Wait for the pod: kubectl wait --for=condition=ready pod -l app=demo-api --timeout=90s

9. Call all endpoints (use port-forward if NodePort doesn't work):
   kubectl port-forward svc/demo-api 8090:8080 &
   sleep 3
   curl -s http://localhost:8090/health
   curl -s http://localhost:8090/version
   curl -s http://localhost:8090/data
   pkill -f "port-forward.*demo-api" 2>/dev/null

10. Write /tmp/demo-api/last_results.json with the actual curl outputs.

11. Write /tmp/demo-api/iteration_1_why.md containing:
    # Iteration 1 — Baseline (v1)
    
    ## What was built
    Minimal FastAPI service with /health, /version, /data endpoints.
    
    ## Endpoints active
    /health, /version, /data
    
    ## Known limitations (opportunities for next iteration)
    - No structured logging (plain print only)
    - No /metrics endpoint
    - No error handling
    - No input validation
    - /data returns hard-coded items
"""


def build_iteration_n_prompt(n: int, pod_logs: str, pod_status: str,
                              prior_results: str, prior_why: str) -> str:
    return f"""
You are on iteration {n} of {NUM_ITERATIONS} in a closed-loop SDLC demo.
The service is already deployed from iteration {n - 1}. Your job is to
OBSERVE its actual behavior and EVOLVE the code to improve it.

# Observed state of the running service

## Current pod status
{pod_status}

## Recent pod logs (last 40 lines)
{pod_logs}

## Previous iteration's endpoint call results
{prior_results}

## Previous iteration's why-file
{prior_why}

# Your task

1. Read /tmp/demo-api/main.py (the current deployed code).

2. Based on the OBSERVED state above, pick ONE concrete improvement.
   Examples (pick one that the telemetry/logs actually motivate):
   - Add structured JSON logging if the logs are plain text and hard to parse
   - Add a /metrics endpoint exposing request counts and latency
   - Add input validation if you see suspicious requests
   - Add error handling around /data
   - Add a /slow endpoint to make latency variation observable
   - Add a request_id field to logs for traceability
   - Add a readiness probe handler distinct from /health

3. Modify /tmp/demo-api/main.py to implement that ONE improvement.

4. UPDATE /version to reflect the new state:
   - bump version to "v{n}"
   - set iteration to {n}
   - append your improvement to improvements_since_v1

5. Save a versioned snapshot: cp /tmp/demo-api/main.py /tmp/demo-api/main.py.v{n}

6. Build: docker build -t demo-api:v{n} /tmp/demo-api/

7. Update k8s.yaml so the Deployment uses image: demo-api:v{n}
   Then apply: kubectl apply -f /tmp/demo-api/k8s.yaml

8. Wait for the rollout: kubectl rollout status deployment/demo-api --timeout=90s

9. Call all endpoints (use port-forward 8090:8080 like before).
   Include any NEW endpoint you added.

10. Write /tmp/demo-api/last_results.json with the actual curl outputs.

11. Write /tmp/demo-api/iteration_{n}_why.md containing:
    # Iteration {n} — v{n}
    
    ## Observed signal that motivated this change
    <quote the exact line/data from pod logs or pod status or prior results
     that drove your decision. Be specific — point at it.>
    
    ## Change made
    <describe the code change>
    
    ## Endpoints active after this iteration
    <list>
    
    ## What to look for next iteration
    <propose what the next iteration should observe and improve>

BE SPECIFIC about which observed signal motivated your choice. The whole point
of this iteration is to demonstrate that the change was driven by telemetry,
not by random choice.
"""


# ============================================================
# Agent runner
# ============================================================

def run_iteration(n: int, task: str) -> None:
    banner = f" ITERATION {n} of {NUM_ITERATIONS} "
    bar = "=" * 70
    print(f"\n{bar}\n{banner.center(70, '=')}\n{bar}\n")

    agent = Agent(
        llm=llm,
        tools=[
            Tool(name="TerminalTool"),
            Tool(name="FileEditorTool"),
        ],
    )
    conversation = Conversation(agent=agent, workspace=WORK_DIR)
    conversation.send_message(task)
    conversation.run()


# ============================================================
# Main loop
# ============================================================

def main():
    import shutil
    if Path(WORK_DIR).exists():
        shutil.rmtree(WORK_DIR)
    Path(WORK_DIR).mkdir(parents=True, exist_ok=True)

    # Also clean any leftover demo-api deployment from prior runs
    subprocess.run(["kubectl", "delete", "deployment", "demo-api",
                    "--ignore-not-found=true"], capture_output=True)
    subprocess.run(["kubectl", "delete", "service", "demo-api",
                    "--ignore-not-found=true"], capture_output=True)

    print(f"Closed-loop SDLC demo — {NUM_ITERATIONS} iterations")

    print(f"Closed-loop SDLC demo — {NUM_ITERATIONS} iterations")
    print(f"Workspace: {WORK_DIR}")
    print(f"Model: {LLM_MODEL}")
    print(f"OTLP: {os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')}")

    # ----- Iteration 1: baseline -----
    run_iteration(1, ITERATION_1_PROMPT)

    # Brief pause so the v1 deployment can emit some logs/traces
    time.sleep(5)

    # ----- Iterations 2..N: feedback-driven -----
    for n in range(2, NUM_ITERATIONS + 1):
        pod_logs = get_pod_logs()
        pod_status = get_pod_status()
        prior_results = get_recent_endpoint_calls()
        prior_why = read_prior_why(n)

        task = build_iteration_n_prompt(n, pod_logs, pod_status, prior_results, prior_why)
        run_iteration(n, task)

        # Pause between iterations so signals settle
        time.sleep(5)

    # ----- Summary -----
    print("\n" + "=" * 70)
    print(" DEMO COMPLETE ".center(70, "="))
    print("=" * 70 + "\n")

    print("Evidence of code evolution — diff the snapshots:")
    for n in range(2, NUM_ITERATIONS + 1):
        print(f"  diff {WORK_DIR}/main.py.v{n - 1} {WORK_DIR}/main.py.v{n}")

    print("\nWhy each iteration changed what it changed:")
    for n in range(1, NUM_ITERATIONS + 1):
        print(f"  cat {WORK_DIR}/iteration_{n}_why.md")

    print("\nLive service shows current iteration:")
    print("  kubectl port-forward svc/demo-api 8090:8080 &")
    print("  curl http://localhost:8090/version")

    print("\nTelemetry — see the LLM calls that drove each iteration:")
    print("  http://localhost:3000  (Traces tab, filter by time)")
    print("=" * 70)


if __name__ == "__main__":
    main()

