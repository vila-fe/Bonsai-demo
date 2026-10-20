# Runtime configuration contract

`config/runtime.yaml` is the **versioned source of truth** for the default model selection and local server endpoints. macOS/Linux shell scripts load it through `scripts/runtime_config.py`; the Windows `start_llama_server.ps1` consumes the same reader's JSON output. No YAML package is installed: the reader uses only the Python standard library.

## Canonical values

| YAML path | Default | Effective environment variable | Consumer |
|---|---:|---|---|
| `model.family` | `bonsai` | `BONSAI_FAMILY` | macOS/Linux setup, download, run, and server scripts; Windows llama server |
| `model.size` | `8B` | `BONSAI_MODEL` | macOS/Linux setup, download, run, and server scripts; Windows llama server |
| `server.llama.host` | `0.0.0.0` | `BONSAI_LLAMA_HOST` | llama.cpp server bind address |
| `server.llama.port` | `8080` | `BONSAI_LLAMA_PORT` | llama.cpp server endpoint |
| `server.mlx.port` | `8081` | `BONSAI_MLX_PORT` | MLX server endpoint |
| `server.openwebui.port` | `9090` | `BONSAI_OPENWEBUI_PORT` | first Open WebUI port to try |
| `server.openwebui.max_port` | `9099` | `BONSAI_OPENWEBUI_MAX_PORT` | last Open WebUI port to try |

> `config/runtime.yaml` changes shared defaults. Use environment variables for a one-off invocation; do not edit the scripts to change an endpoint.

## Precedence and compatibility

The reader applies a **non-empty** environment variable over the matching YAML value. An unset or empty variable therefore retains the committed default, matching the previous shell `${VAR:-default}` behavior for `BONSAI_FAMILY` and `BONSAI_MODEL`. `common.sh` also passes a variable assigned before it is sourced, even if the caller did not export it yet.

Existing model-selection invocations remain valid:

```bash
BONSAI_FAMILY=ternary BONSAI_MODEL=4B ./setup.sh
BONSAI_MODEL=1.7B ./scripts/run_llama.sh -p "Who are you?"
```

Server endpoints can now be overridden without editing a script:

```bash
BONSAI_LLAMA_HOST=127.0.0.1 BONSAI_LLAMA_PORT=18080 ./scripts/start_llama_server.sh
BONSAI_OPENWEBUI_PORT=19090 BONSAI_OPENWEBUI_MAX_PORT=19099 ./scripts/start_openwebui.sh
```

## Validation

The reader merges defaults and overrides, then fails before any server starts if the effective configuration is invalid:

- `BONSAI_FAMILY` must be `bonsai`, `ternary`, or `all`; `BONSAI_MODEL` must be `8B`, `4B`, `1.7B`, or `all`.
- `all` remains valid for setup/download expansion only. Run and server scripts reject it because they require a concrete model.
- `BONSAI_LLAMA_HOST` must be `localhost` or an IPv4/IPv6 address.
- Every port must be a decimal integer from `1` through `65535`.
- The llama and MLX ports must differ; the entire Open WebUI range must exclude both backend ports, and its maximum must not be smaller than its starting port.
- The committed YAML must have the exact documented mapping shape. Unknown, missing, duplicate, quoted, tab-indented, or otherwise unsupported YAML constructs fail closed rather than being ignored.

The intentionally small YAML subset supports only the plain, two-space-indented mapping used by `config/runtime.yaml`. Keep values as unquoted plain scalars. This is a deliberate dependency boundary, not a general-purpose YAML parser.

## Inspecting or consuming values

Validate and inspect the merged configuration:

```bash
python3 scripts/runtime_config.py --json
```

For a POSIX shell consumer, the helper prints only known variable names with `shlex.quote`-escaped values:

```bash
eval "$(python3 scripts/runtime_config.py --shell)"
printf '%s\n' "$BONSAI_LLAMA_HOST:$BONSAI_LLAMA_PORT"
```

`common.sh` performs this operation automatically for the macOS/Linux scripts. The explicit command is useful for debugging configuration in CI or before launching a server.
