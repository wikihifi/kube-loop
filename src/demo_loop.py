import os
import openlit
from openhands.sdk import LLM, Agent, Conversation
from openhands.sdk.tool import Tool, register_tool
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

# Register tools (required for openhands-sdk 1.22.x)
register_tool("TerminalTool", TerminalTool)
register_tool("FileEditorTool", FileEditorTool)

# Initialize telemetry
openlit.init(otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))

llm = LLM(model=os.getenv("LLM_MODEL"), api_key=os.getenv("LLM_API_KEY"))
COLIMA_IP = os.getenv("COLIMA_IP", "192.168.64.2")
WORK_DIR = "/tmp/demo-api"

# Ensure workspace exists before the agent runs
os.makedirs(WORK_DIR, exist_ok=True)

ITERATION_1_TASK = f"""
You are an SDLC automation agent. Execute these steps in order.
After each step, briefly confirm it succeeded before moving on.

1. Create /tmp/demo-api/main.py with a FastAPI app exposing:
   - GET /health  -> returns {{"status": "ok", "version": 1}}
   - GET /data    -> returns {{"items": [1, 2, 3], "count": 3}}

2. Create /tmp/demo-api/requirements.txt with:
   fastapi
   uvicorn

3. Create /tmp/demo-api/Dockerfile:
   FROM python:3.12-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY main.py .
   EXPOSE 8080
   CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

4. Create /tmp/demo-api/k8s.yaml with a Deployment and a NodePort Service.
   Critical settings:
   - image: demo-api:latest
   - imagePullPolicy: IfNotPresent      (Colima k3s uses local Docker images automatically)
   - container port: 8080
   - service type: NodePort
   - nodePort: 30080
   - labels: app=demo-api

5. Build the Docker image:
   docker build -t demo-api:latest /tmp/demo-api/

6. Apply the manifest:
   kubectl apply -f /tmp/demo-api/k8s.yaml

7. Wait for the pod to be ready:
   kubectl wait --for=condition=ready pod -l app=demo-api --timeout=60s

8. Show the pod and service status:
   kubectl get pods -l app=demo-api
   kubectl get svc demo-api

9. Call both endpoints via the Colima VM IP ({COLIMA_IP}):
   curl -s http://{COLIMA_IP}:30080/health
   curl -s http://{COLIMA_IP}:30080/data

   If those time out, use port-forward as fallback:
   kubectl port-forward svc/demo-api 8090:8080 &
   sleep 2
   curl -s http://localhost:8090/health
   curl -s http://localhost:8090/data
   kill %1   # stop the port-forward

10. Write /tmp/demo-api/results.json containing:
    {{
      "health_response": "<actual curl output>",
      "data_response": "<actual curl output>",
      "pod_status": "<output of kubectl get pods>",
      "endpoint_used": "<NodePort or port-forward>"
    }}
"""

ITERATION_2_TASK = """
The previous iteration deployed a FastAPI service to Kubernetes and recorded
results in /tmp/demo-api/results.json.

Now do the analysis loop:

1. Read /tmp/demo-api/results.json and parse it

2. Get the pod logs:
   kubectl logs -l app=demo-api --tail=30

3. Verify both /health and /data returned the expected JSON shapes

4. Write /tmp/demo-api/analysis.md containing:
   - Summary: what was deployed and which endpoint method worked
   - Verification: were the responses correct?
   - Logs: 2-3 line summary of what the pod logs show
   - Issues: anything weird or unexpected
   - Improvements: three concrete next-iteration improvements
     (e.g. add /metrics endpoint, add structured logging, add liveness probe)
"""


def run_agent(task: str, label: str) -> None:
    print(f"\n{'='*70}\n  {label}\n{'='*70}\n")

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


# Run the loop
print(f"Starting demo loop. Colima IP: {COLIMA_IP}")
run_agent(ITERATION_1_TASK, "ITERATION 1 — Build & Deploy")
run_agent(ITERATION_2_TASK, "ITERATION 2 — Analyze & Plan")

print("\n" + "="*70)
print("DEMO COMPLETE")
print("="*70)
print(f"  Results:    /tmp/demo-api/results.json")
print(f"  Analysis:   /tmp/demo-api/analysis.md")
print(f"  Live API:   http://{COLIMA_IP}:30080/health")
print(f"  Telemetry:  http://localhost:3000")
