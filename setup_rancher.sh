#!/usr/bin/env bash
#
# setup.sh — One-shot setup for agentic-sdlc-loop (Rancher Desktop edition)
#
# Installs system dependencies, ensures Rancher Desktop with Kubernetes is
# running, installs OpenLIT into the cluster, sets up a Python venv, and
# installs Python dependencies from requirements.txt.
#
# Why Rancher Desktop: pre-built binaries for macOS (including macOS 13),
# bundles its own VM + k3s, no Homebrew-built QEMU required.
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# Environment variables (optional):
#   SKIP_BREW=1          Skip Homebrew installs
#   SKIP_RANCHER=1       Skip Rancher Desktop install (e.g. already running)
#   SKIP_OPENLIT=1       Skip OpenLIT install
#   SKIP_PYTHON=1        Skip Python venv and pip installs
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
 
trap 'err "Script failed at line $LINENO (exit code $?)"' ERR
 
# ----- config -----
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
# Step 1: System dependencies via Homebrew (pre-built only)
# ============================================================
if [[ "${SKIP_BREW:-}" != "1" ]]; then
    log "Installing system dependencies via Homebrew..."
 
    brew_install() {
        local pkg="$1"
        if brew list --formula "$pkg" >/dev/null 2>&1; then
            ok "$pkg already installed"
        else
            log "Installing $pkg..."
            brew install "$pkg" || warn "$pkg install failed — continuing"
        fi
    }
 
    # CLI dependencies (all have pre-built bottles)
    brew_install kubectl
    brew_install helm
    brew_install "node@${NODE_VERSION}"
    brew_install "python@${PYTHON_VERSION}"
    brew_install jq
 
    # Add node@20 to PATH for this session
    if ! command -v node >/dev/null 2>&1; then
        export PATH="/opt/homebrew/opt/node@${NODE_VERSION}/bin:$PATH"
    fi
else
    warn "Skipping Homebrew installs (SKIP_BREW=1)"
fi
 
# ============================================================
# Step 2: Install and start Rancher Desktop
# ============================================================
if [[ "${SKIP_RANCHER:-}" != "1" ]]; then
    log "Installing Rancher Desktop..."
 
    if brew list --cask rancher >/dev/null 2>&1; then
        ok "Rancher Desktop already installed"
    else
        log "Downloading and installing Rancher Desktop (this may take a few minutes)..."
        brew install --cask rancher
    fi
 
    # Open Rancher Desktop if not running
    if ! pgrep -f "Rancher Desktop" >/dev/null; then
        log "Starting Rancher Desktop..."
        open -a "Rancher Desktop"
 
        echo
        warn "Rancher Desktop is starting for the first time."
        echo "  Please complete the first-run setup in the UI:"
        echo "    1. Choose 'dockerd (moby)' as the container engine"
        echo "    2. Enable Kubernetes (k3s)"
        echo "    3. Accept the default Kubernetes version"
        echo "    4. Click 'Accept' to apply settings"
        echo
        echo "Waiting for Rancher Desktop's Kubernetes to become ready..."
        echo "(This can take 2-5 minutes on first launch)"
        echo
    fi
 
    # Wait for kubectl to be able to reach the rancher-desktop cluster
    log "Waiting for kubectl access to rancher-desktop context..."
    READY=0
    for i in $(seq 1 60); do
        if kubectl --context rancher-desktop get nodes >/dev/null 2>&1; then
            READY=1
            break
        fi
        printf "."
        sleep 10
    done
    echo
 
    if [[ "$READY" != "1" ]]; then
        err "Rancher Desktop's Kubernetes did not become ready within 10 minutes."
        err "Open Rancher Desktop and verify: Settings → Kubernetes → Enable Kubernetes"
        err "Then re-run: SKIP_BREW=1 ./setup.sh"
        exit 1
    fi
 
    # Switch kubectl to the rancher-desktop context
    kubectl config use-context rancher-desktop
 
    ok "Rancher Desktop Kubernetes is ready"
    kubectl get nodes
else
    warn "Skipping Rancher Desktop install (SKIP_RANCHER=1)"
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
    kubectl wait --for=condition=ready pod openlit-0 \
        -n openlit --timeout=180s 2>/dev/null || \
    kubectl wait --for=condition=ready pod -l app.kubernetes.io/name=openlit \
        -n openlit --timeout=180s 2>/dev/null || true
 
    ok "OpenLIT installed"
else
    warn "Skipping OpenLIT install (SKIP_OPENLIT=1)"
fi
 
# ============================================================
# Step 4: Python venv + dependencies
# ============================================================
if [[ "${SKIP_PYTHON:-}" != "1" ]]; then
    log "Setting up Python virtual environment..."
 
    if [[ ! -d ".venv" ]]; then
        python${PYTHON_VERSION} -m venv .venv
        ok "Created .venv"
    else
        ok ".venv already exists"
    fi
 
    # shellcheck disable=SC1091
    source .venv/bin/activate
 
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
else
    warn "Skipping Python setup (SKIP_PYTHON=1)"
fi
 
# ============================================================
# Step 5: Write .env template
# ============================================================
if [[ ! -f ".env" ]]; then
    log "Writing .env template..."
    cat > .env <<'EOF'
# Fill in your LLM API key below
LLM_API_KEY=your_api_key_here
LLM_MODEL=anthropic/claude-sonnet-4-6
# Alternative: openai/gpt-4o
 
# OpenLIT telemetry endpoint
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
EOF
    ok ".env template created — edit it with your API key"
else
    ok ".env already exists"
fi
 
# ============================================================
# Step 6: Start port-forwards
# ============================================================
log "Starting port-forwards to OpenLIT..."
 
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
echo "OpenLIT UI:    http://localhost:3000"
echo "  Login:       user@openlit.io / openlituser"
echo
echo "Cluster info:  kubectl get nodes"
echo "Stop cluster:  open Rancher Desktop → Quit"
echo "Reset cluster: open Rancher Desktop → Troubleshooting → Reset Kubernetes"