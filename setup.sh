#!/usr/bin/env bash
#
# setup.sh — One-shot setup for agentic-sdlc-loop
#
# Installs all system dependencies, starts Colima with Kubernetes,
# installs OpenLIT into the cluster, sets up a Python venv, and
# installs Python dependencies from requirements.txt.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# Environment variables (optional):
#   SKIP_BREW=1          Skip Homebrew installs (if you've already done them)
#   SKIP_COLIMA=1        Skip Colima start (if already running)
#   SKIP_OPENLIT=1       Skip OpenLIT install (if already installed)
#   COLIMA_CPU=4         CPU cores for Colima VM
#   COLIMA_MEMORY=10     RAM (GB) for Colima VM
#   COLIMA_DISK=60       Disk (GB) for Colima VM
#
 
set -euo pipefail
 
# ----- styling -----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'
 
log()  { echo -e "${BLUE}==>${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC}  $*"; }
err()  { echo -e "${RED}✗${NC} $*" >&2; }
 
# ----- config -----
COLIMA_CPU="${COLIMA_CPU:-4}"
COLIMA_MEMORY="${COLIMA_MEMORY:-10}"
COLIMA_DISK="${COLIMA_DISK:-60}"
PYTHON_VERSION="3.12"
NODE_VERSION="20"
 
# ----- preflight -----
if [[ "$(uname)" != "Darwin" ]]; then
    err "This script is for macOS. Detected: $(uname)"
    exit 1
fi
 
if ! command -v brew >/dev/null 2>&1; then
    err "Homebrew is required. Install from https://brew.sh first."
    exit 1
fi
 
# ============================================================
# Step 1: System dependencies via Homebrew
# ============================================================
if [[ "${SKIP_BREW:-}" != "1" ]]; then
    log "Installing system dependencies via Homebrew..."
 
    brew_install() {
        local pkg="$1"
        if brew list --formula "$pkg" >/dev/null 2>&1; then
            ok "$pkg already installed"
        else
            log "Installing $pkg..."
            brew install "$pkg"
        fi
    }
 
    brew_install colima
    brew_install docker
    brew_install kubectl
    brew_install helm
    brew_install "node@${NODE_VERSION}"
    brew_install "python@${PYTHON_VERSION}"
    brew_install jq
 
    # Add node@20 to PATH for this session if not already
    if ! command -v node >/dev/null 2>&1; then
        export PATH="/opt/homebrew/opt/node@${NODE_VERSION}/bin:$PATH"
    fi
 
    # Install uv (Python package manager) if missing
    if ! command -v uv >/dev/null 2>&1; then
        log "Installing uv (Python package manager)..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        source "$HOME/.cargo/env" 2>/dev/null || true
    else
        ok "uv already installed"
    fi
else
    warn "Skipping Homebrew installs (SKIP_BREW=1)"
fi
 
# ============================================================
# Step 2: Start Colima with Kubernetes
# ============================================================
if [[ "${SKIP_COLIMA:-}" != "1" ]]; then
    log "Starting Colima with Kubernetes..."
 
    if colima status 2>/dev/null | grep -q "Running"; then
        ok "Colima is already running"
    else
        colima start \
            --cpu "${COLIMA_CPU}" \
            --memory "${COLIMA_MEMORY}" \
            --disk "${COLIMA_DISK}" \
            --kubernetes \
            --network-address
    fi
 
    log "Verifying cluster is accessible..."
    kubectl get nodes
    ok "Kubernetes cluster ready"
else
    warn "Skipping Colima start (SKIP_COLIMA=1)"
fi
 
# ============================================================
# Step 3: Install OpenLIT
# ============================================================
if [[ "${SKIP_OPENLIT:-}" != "1" ]]; then
    log "Installing OpenLIT into the cluster..."
 
    if ! helm repo list 2>/dev/null | grep -q "^openlit"; then
        helm repo add openlit https://openlit.github.io/helm/
    fi
    helm repo update
 
    if helm list -n openlit 2>/dev/null | grep -q "^openlit"; then
        ok "OpenLIT already installed"
    else
        helm install openlit openlit/openlit \
            --namespace openlit \
            --create-namespace \
            --wait \
            --timeout 10m
    fi
 
    log "Waiting for OpenLIT pods to be ready..."
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=openlit \
        -n openlit --timeout=180s 2>/dev/null || \
    kubectl wait --for=condition=ready pod openlit-0 \
        -n openlit --timeout=180s 2>/dev/null || true
 
    ok "OpenLIT installed"
    log "UI:  http://localhost:3000  (default: user@openlit.io / openlituser)"
    log "OTLP: http://localhost:4318"
else
    warn "Skipping OpenLIT install (SKIP_OPENLIT=1)"
fi
 
# ============================================================
# Step 4: Python venv + dependencies
# ============================================================
log "Setting up Python virtual environment..."
 
if [[ ! -d ".venv" ]]; then
    python${PYTHON_VERSION} -m venv .venv
    ok "Created .venv"
else
    ok ".venv already exists"
fi
 
# shellcheck disable=SC1091
source .venv/bin/activate
 
# Create requirements.txt if missing
if [[ ! -f "requirements.txt" ]]; then
    log "Creating requirements.txt..."
    cat > requirements.txt <<'EOF'
openhands-sdk
openhands-tools
openlit
EOF
    ok "requirements.txt created"
fi
 
log "Installing Python dependencies..."
pip install --upgrade pip --quiet
pip install -r requirements.txt
ok "Python dependencies installed"
 
# ============================================================
# Step 5: Capture Colima IP and write .env template
# ============================================================
log "Detecting Colima VM IP..."
 
COLIMA_IP=$(colima list 2>/dev/null | awk 'NR==2 {print $8}' || echo "")
if [[ -z "$COLIMA_IP" ]]; then
    warn "Could not auto-detect Colima IP. Run 'colima list' manually."
    COLIMA_IP="192.168.64.2"
fi
ok "Colima VM IP: $COLIMA_IP"
 
if [[ ! -f ".env" ]]; then
    log "Writing .env template..."
    cat > .env <<EOF
# Fill in your LLM API key below
LLM_API_KEY=your_api_key_here
LLM_MODEL=anthropic/claude-sonnet-4-6
# Alternative: openai/gpt-4o
 
# OpenLIT telemetry endpoint
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
 
# Colima VM IP (auto-detected)
COLIMA_IP=${COLIMA_IP}
EOF
    ok ".env template created — edit it with your API key"
else
    ok ".env already exists"
fi
 
# ============================================================
# Step 6: Start port-forwards
# ============================================================
log "Starting port-forwards to OpenLIT..."
 
# Kill any existing forwards on these ports
pkill -f "kubectl port-forward.*openlit.*3000" 2>/dev/null || true
pkill -f "kubectl port-forward.*openlit.*4318" 2>/dev/null || true
sleep 1
 
kubectl port-forward svc/openlit 3000:3000 -n openlit \
    > /tmp/openlit-ui-forward.log 2>&1 &
kubectl port-forward svc/openlit 4318:4318 -n openlit \
    > /tmp/openlit-otlp-forward.log 2>&1 &
sleep 2
 
ok "Port-forwards running (logs: /tmp/openlit-*-forward.log)"
 
# ============================================================
# Done
# ============================================================
echo
echo -e "${GREEN}===========================================${NC}"
echo -e "${GREEN}  Setup complete!${NC}"
echo -e "${GREEN}===========================================${NC}"
echo
echo "Next steps:"
echo "  1. Edit .env and add your LLM_API_KEY"
echo "  2. source .venv/bin/activate"
echo "  3. set -a; source .env; set +a"
echo "  4. python demo_loop.py"
echo
echo "OpenLIT UI: http://localhost:3000"
echo "  Login:    user@openlit.io / openlituser"
echo
echo "To stop the cluster later:  colima stop"
echo "To tear it down:            colima delete"
