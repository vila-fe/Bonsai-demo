# Canonical Runtime Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize Unix runtime defaults for model selection and local server endpoints in a versioned YAML file without adding a YAML dependency.

**Architecture:** `config/runtime.yaml` will be the sole default source. A standard-library Python reader will parse a deliberately restricted, documented YAML mapping; merge named `BONSAI_*` environment overrides; validate the effective configuration; and emit safely quoted POSIX shell exports. `scripts/common.sh` will load those exports, while setup and start scripts consume variables rather than redeclaring defaults.

**Tech Stack:** POSIX `sh`, Python 3 standard library (`argparse`, `json`, `pathlib`, `shlex`, `subprocess`, `unittest`), YAML plain mappings.

**Spec:** User task: canonical `config/runtime.yaml`, validated lightweight reader, environment compatibility, TDD for defaults/overrides/validation, documentation, syntax/YAML validation, atomic local commits, no push.

## Global Constraints

- Work only in `/home/ubuntu/repo-audit-12-Bonsai-demo`.
- Create branch `refactor/canonical-runtime-config`; do not push.
- Do not add a YAML package or change inference parameters.
- Keep `BONSAI_FAMILY` and `BONSAI_MODEL` overrides compatible; document added server override names.
- Runtime scripts must reject invalid model/family/port values before starting a server.
- Run Python, YAML, shell, CI-equivalent, and lockfile verification before completion.

---

### Task 1: Define and test the reader contract

**Files:**
- Create: `tests/test_runtime_config.py`
- Create: `config/runtime.yaml`
- Create: `scripts/runtime_config.py`

**Interfaces:**
- Consumes: `config/runtime.yaml` and optional environment overrides.
- Produces: `python3 scripts/runtime_config.py --json` for inspection and `--shell` with quoted `export KEY=VALUE` lines.

- [ ] **Step 1: Write failing tests**

```python
self.assertEqual(self.run_config().stdout_json["BONSAI_FAMILY"], "bonsai")
self.assertEqual(self.run_config(env={"BONSAI_MODEL": "4B"}).stdout_json["BONSAI_MODEL"], "4B")
self.assert_config_error({"BONSAI_LLAMA_PORT": "70000"}, "BONSAI_LLAMA_PORT")
```

- [ ] **Step 2: Run the tests to verify RED**

Run: `python3 -m unittest tests/test_runtime_config.py -v`

Expected: failure because `scripts/runtime_config.py` and `config/runtime.yaml` do not yet exist.

- [ ] **Step 3: Implement the minimum reader and canonical mapping**

```python
parser.add_argument("--shell", action="store_true")
parser.add_argument("--json", action="store_true")
values = load_validate_and_merge(config_path, os.environ)
```

The parser accepts only indented plain-scalar maps required by this committed YAML and fails closed for other YAML features. Validation permits existing family/model values, validates every port as an integer in `1..65535`, prevents endpoint collisions, and requires the Open WebUI upper port to be at least its starting port.

- [ ] **Step 4: Run the tests to verify GREEN**

Run: `python3 -m unittest tests/test_runtime_config.py -v`

Expected: all default, override, invalid-model, invalid-family, invalid-port, and shell-export tests pass.

- [ ] **Step 5: Commit the tested runtime-config core**

```bash
git add config/runtime.yaml scripts/runtime_config.py tests/test_runtime_config.py
git commit -m "refactor: add canonical runtime config reader"
```

### Task 2: Consume canonical values in Unix scripts

**Files:**
- Modify: `scripts/common.sh`
- Modify: `setup.sh`
- Modify: `scripts/start_llama_server.sh`
- Modify: `scripts/start_mlx_server.sh`
- Modify: `scripts/start_openwebui.sh`
- Modify: `.github/workflows/check-env-vars.yml`

**Interfaces:**
- Consumes: exported `BONSAI_FAMILY`, `BONSAI_MODEL`, `BONSAI_LLAMA_HOST`, `BONSAI_LLAMA_PORT`, `BONSAI_MLX_PORT`, `BONSAI_OPENWEBUI_PORT`, and `BONSAI_OPENWEBUI_MAX_PORT`.
- Produces: unchanged model-derived paths and server CLI invocation behavior, using canonical effective endpoints.

- [ ] **Step 1: Write/extend a failing integration test**

```python
completed = subprocess.run(
    ["sh", "-c", 'eval "$(python3 scripts/runtime_config.py --shell)"; printf "%s" "$BONSAI_LLAMA_PORT"'],
    text=True, capture_output=True, check=True,
)
self.assertEqual(completed.stdout, "8080")
```

- [ ] **Step 2: Run it to demonstrate the expected contract boundary**

Run: `python3 -m unittest tests/test_runtime_config.py -v`

Expected: the integration assertion fails until the reader supplies safe shell exports.

- [ ] **Step 3: Replace duplicate script defaults with loaded values**

```sh
_runtime_exports="$(python3 "$_runtime_config_helper" --shell)" || return 1
eval "$_runtime_exports"
PORT="$BONSAI_LLAMA_PORT"
```

Remove the setup-local family/model defaults. Preserve `all` for setup/download but reject it from runtime through the existing concrete-model assertion.

- [ ] **Step 4: Run focused and CI-equivalent tests**

Run: `python3 -m unittest tests/test_runtime_config.py -v && sh -n scripts/common.sh setup.sh scripts/start_llama_server.sh scripts/start_mlx_server.sh scripts/start_openwebui.sh && python3 -m unittest discover -s tests -v`

Expected: all commands exit 0.

- [ ] **Step 5: Commit script consumption changes**

```bash
git add scripts/common.sh setup.sh scripts/start_llama_server.sh scripts/start_mlx_server.sh scripts/start_openwebui.sh .github/workflows/check-env-vars.yml
git commit -m "refactor: load runtime defaults from canonical config"
```

### Task 3: Document and verify the operational contract

**Files:**
- Create: `docs/runtime-configuration.md`
- Modify: `README.md`

**Interfaces:**
- Documents: source-of-truth location, supported YAML subset, precedence, valid values, environment overrides, validation rules, and inspection command.

- [ ] **Step 1: Write contract documentation**

```markdown
`config/runtime.yaml` provides committed defaults. A non-empty listed environment
variable wins. The reader validates the merged configuration and emits POSIX-safe
exports; invalid input terminates before a script can start a process.
```

- [ ] **Step 2: Link the contract from the README**

```markdown
See [Runtime configuration](docs/runtime-configuration.md) for server endpoint overrides and validation.
```

- [ ] **Step 3: Run final verification**

Run: `python3 -m unittest discover -s tests -v && python3 scripts/runtime_config.py --json && python3 scripts/runtime_config.py --shell >/dev/null && sh -n setup.sh scripts/*.sh && python3 -m py_compile scripts/runtime_config.py scripts/mlx_generate.py && git diff --check && git status --short --branch`

Expected: all validation commands exit 0; `uv lock --check` is unnecessary because `pyproject.toml` is unchanged.

- [ ] **Step 4: Commit documentation**

```bash
git add docs/runtime-configuration.md README.md docs/superpowers/plans/2026-10-20-canonical-runtime-config.md
git commit -m "docs: document canonical runtime configuration"
```
