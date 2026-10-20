#!/bin/sh
# Shared helpers for Bonsai demo scripts.
# Source this file: . "$(dirname "$0")/common.sh"

# ── Canonical runtime configuration ──
# config/runtime.yaml contains committed defaults. Non-empty BONSAI_* variables
# override it. The helper validates the effective values before emitting only
# safely quoted export statements for eval below.
_load_runtime_config() {
    if [ -n "${BONSAI_RUNTIME_CONFIG_HELPER:-}" ]; then
        _runtime_config_helper="$BONSAI_RUNTIME_CONFIG_HELPER"
    elif [ -n "${SCRIPT_DIR:-}" ] && [ -f "$SCRIPT_DIR/runtime_config.py" ]; then
        _runtime_config_helper="$SCRIPT_DIR/runtime_config.py"
    elif [ -n "${SCRIPT_DIR:-}" ] && [ -f "$SCRIPT_DIR/scripts/runtime_config.py" ]; then
        _runtime_config_helper="$SCRIPT_DIR/scripts/runtime_config.py"
    elif [ -f "scripts/runtime_config.py" ]; then
        _runtime_config_helper="scripts/runtime_config.py"
    else
        printf '%s\n' "[ERR] runtime_config.py not found; cannot load config/runtime.yaml." >&2
        return 1
    fi

    if ! command -v python3 >/dev/null 2>&1; then
        printf '%s\n' "[ERR] python3 is required to load config/runtime.yaml." >&2
        return 1
    fi
    _runtime_config_exports="$(
        BONSAI_FAMILY="${BONSAI_FAMILY:-}" \
        BONSAI_MODEL="${BONSAI_MODEL:-}" \
        BONSAI_LLAMA_HOST="${BONSAI_LLAMA_HOST:-}" \
        BONSAI_LLAMA_PORT="${BONSAI_LLAMA_PORT:-}" \
        BONSAI_MLX_PORT="${BONSAI_MLX_PORT:-}" \
        BONSAI_OPENWEBUI_PORT="${BONSAI_OPENWEBUI_PORT:-}" \
        BONSAI_OPENWEBUI_MAX_PORT="${BONSAI_OPENWEBUI_MAX_PORT:-}" \
        python3 "$_runtime_config_helper" --shell
    )" || return 1
    # shellcheck disable=SC2086
    eval "$_runtime_config_exports"
    unset _runtime_config_helper _runtime_config_exports
}

if ! _load_runtime_config; then
    unset -f _load_runtime_config 2>/dev/null || true
    return 1 2>/dev/null || exit 1
fi
unset -f _load_runtime_config 2>/dev/null || true

# Derived paths default to empty so an invalid family or "all" never produces
# a stale/glob-able path (e.g. `ls /*.gguf`). Concrete paths are only set when
# the (family, size) pair is a valid concrete combination — runtime scripts
# call assert_*_downloaded which validates and gives a clear error.
GGUF_MODEL_DIR=""
MLX_MODEL_DIR=""
BONSAI_DISPLAY="(family=${BONSAI_FAMILY} size=${BONSAI_MODEL})"

case "$BONSAI_MODEL" in
    8B|4B|1.7B)
        case "$BONSAI_FAMILY" in
            bonsai)
                GGUF_MODEL_DIR="models/gguf/${BONSAI_MODEL}"
                MLX_MODEL_DIR="models/Bonsai-${BONSAI_MODEL}-mlx"
                BONSAI_DISPLAY="Bonsai-${BONSAI_MODEL}"
                ;;
            ternary)
                GGUF_MODEL_DIR="models/ternary-gguf/${BONSAI_MODEL}"
                MLX_MODEL_DIR="models/Ternary-Bonsai-${BONSAI_MODEL}-mlx-2bit"
                BONSAI_DISPLAY="Ternary-Bonsai-${BONSAI_MODEL}"
                ;;
            # Anything else, including "all": paths stay empty; assert_valid_model
            # will reject invalid families when called.
        esac
        ;;
    # Anything else, including "all": paths stay empty until validated.
esac

# Configuration has already been validated by runtime_config.py while sourcing
# this file. Keep this public no-op for compatibility with existing callers.
assert_valid_model() {
    :
}

# Reject invalid values and the download-only "all" at runtime with a clear
# message. Called by assert_gguf_downloaded / assert_mlx_downloaded so they're
# safe to call even if the run script forgot to call assert_valid_model first.
_assert_concrete_model() {
    assert_valid_model
    if [ "$BONSAI_FAMILY" = "all" ] || [ "$BONSAI_MODEL" = "all" ]; then
        err "BONSAI_FAMILY='all' / BONSAI_MODEL='all' is only valid for setup/download."
        echo "  Pick a concrete family/size for run scripts, e.g.:"
        echo "    BONSAI_FAMILY=bonsai BONSAI_MODEL=8B ./scripts/run_llama.sh ..."
        exit 1
    fi
}

# Check GGUF model is downloaded — prompts to download if missing
assert_gguf_downloaded() {
    _assert_concrete_model
    if ! ls "$GGUF_MODEL_DIR"/*.gguf >/dev/null 2>&1; then
        err "GGUF model not found for ${BONSAI_DISPLAY} (expected in ${GGUF_MODEL_DIR}/)."
        echo "  Download it with:"
        echo "    BONSAI_FAMILY=${BONSAI_FAMILY} BONSAI_MODEL=${BONSAI_MODEL} ./scripts/download_models.sh"
        exit 1
    fi
}

# Check MLX model is downloaded — prompts to download if missing
assert_mlx_downloaded() {
    _assert_concrete_model
    if [ ! -f "$MLX_MODEL_DIR/config.json" ]; then
        err "MLX model not found for ${BONSAI_DISPLAY} (expected in ${MLX_MODEL_DIR}/)."
        echo "  Download it with:"
        echo "    BONSAI_FAMILY=${BONSAI_FAMILY} BONSAI_MODEL=${BONSAI_MODEL} ./scripts/download_models.sh"
        exit 1
    fi
}

# ── Colors ──
if [ -t 1 ]; then
    _CLR_GREEN="\033[32m"
    _CLR_YELLOW="\033[33m"
    _CLR_RED="\033[31m"
    _CLR_CYAN="\033[36m"
    _CLR_RESET="\033[0m"
else
    _CLR_GREEN="" _CLR_YELLOW="" _CLR_RED="" _CLR_CYAN="" _CLR_RESET=""
fi

info()  { printf "${_CLR_GREEN}[OK]${_CLR_RESET}   %s\n" "$*"; }
warn()  { printf "${_CLR_YELLOW}[WARN]${_CLR_RESET} %s\n" "$*"; }
err()   { printf "${_CLR_RED}[ERR]${_CLR_RESET}  %s\n" "$*" >&2; }
step()  { printf "${_CLR_CYAN}==>    %s${_CLR_RESET}\n" "$*"; }

# ── download(url, dest) — supports curl and wget ──
download() {
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$2" "$1"
    else
        err "Neither curl nor wget found. Install one and re-run."
        exit 1
    fi
}

# ── Smart context size for llama.cpp ──
# Default: -c 0 lets llama.cpp's --fit auto-size KV cache to available memory.
# Fallback: if -c 0 is not supported, pick a safe value from system RAM.
# Max context: 65536.
# Memory = ~1.1 GB weights + ~140 bytes/token KV cache + activations.
#   8 GB  → -c  8192  (~2.5 GB total, leaves ~5 GB for OS)
#  16 GB  → -c 32768  (~5.9 GB total, leaves ~10 GB for OS)
#  24 GB+ → -c 65536  (~10.5 GB total, leaves ~13+ GB for OS)

CTX_SIZE_DEFAULT=0

# GPU layer offload: 99 = offload all layers to GPU, 0 = CPU only.
# Override with BONSAI_NGL env var if needed.
bonsai_llama_ngl() {
    if [ -n "${BONSAI_NGL:-}" ]; then
        echo "$BONSAI_NGL"
    elif [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "x86_64" ]; then
        echo 0  # Intel Mac — no Metal
    elif command -v nvidia-smi >/dev/null 2>&1 || command -v nvcc >/dev/null 2>&1; then
        echo 99  # CUDA
    elif command -v rocminfo >/dev/null 2>&1 || command -v hipcc >/dev/null 2>&1; then
        echo 99  # ROCm/HIP
    elif command -v vulkaninfo >/dev/null 2>&1; then
        echo 99  # Vulkan
    elif [ "$(uname -s)" = "Darwin" ]; then
        echo 99  # Apple Silicon — Metal
    else
        echo 0   # CPU only
    fi
}

# MLX is Apple Silicon only; skip on Intel Mac or when BONSAI_SKIP_MLX=1.
bonsai_should_skip_mlx() {
    case "${BONSAI_SKIP_MLX:-}" in
        1|true|yes) return 0 ;;
        0|false|no) return 1 ;;
        *)
            [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "x86_64" ] && return 0
            return 1 ;;
    esac
}

get_context_size_fallback() {
    if [ "$(uname -s)" = "Darwin" ]; then
        _mem_gb=$(( $(sysctl -n hw.memsize) / 1073741824 ))
    else
        _mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null)
        _mem_gb=$(( ${_mem_kb:-0} / 1048576 ))
    fi

    if [ "$_mem_gb" -le 8 ] 2>/dev/null; then
        echo 8192
    elif [ "$_mem_gb" -le 18 ] 2>/dev/null; then
        echo 32768
    else
        echo 65536
    fi
}

# ── Resolve DEMO_DIR (parent of scripts/) ──
resolve_demo_dir() {
    _script_dir="$(cd "$(dirname "$0")" && pwd)"
    echo "$(cd "$_script_dir/.." && pwd)"
}

# ── Ensure .venv is active (for MLX / Python scripts) ──
ensure_venv() {
    _demo="$1"
    if [ -z "$VIRTUAL_ENV" ] && [ -f "$_demo/.venv/bin/activate" ]; then
        . "$_demo/.venv/bin/activate"
    fi
    if [ -z "$VIRTUAL_ENV" ]; then
        err "Python venv not found. Run ./setup.sh first."
        exit 1
    fi
}
