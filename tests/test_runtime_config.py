"""Behavioral contract tests for the lightweight runtime configuration reader."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPOSITORY = Path(__file__).resolve().parents[1]
READER = REPOSITORY / "scripts" / "runtime_config.py"
CONFIG = REPOSITORY / "config" / "runtime.yaml"
RUNTIME_ENV_NAMES = (
    "BONSAI_FAMILY",
    "BONSAI_MODEL",
    "BONSAI_LLAMA_HOST",
    "BONSAI_LLAMA_PORT",
    "BONSAI_MLX_PORT",
    "BONSAI_OPENWEBUI_PORT",
    "BONSAI_OPENWEBUI_MAX_PORT",
)


class RuntimeConfigReaderTests(unittest.TestCase):
    """Tests the reader at its command-line boundary, not its implementation."""

    def run_reader(self, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        command_env = os.environ.copy()
        for name in RUNTIME_ENV_NAMES:
            command_env.pop(name, None)
        if env:
            command_env.update(env)
        return subprocess.run(
            ["python3", str(READER), *arguments],
            cwd=REPOSITORY,
            env=command_env,
            text=True,
            capture_output=True,
            check=False,
        )

    def read_json(self, env: dict[str, str] | None = None) -> dict[str, str]:
        completed = self.run_reader("--json", env=env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def assert_config_error(self, env: dict[str, str], message_fragment: str) -> None:
        completed = self.run_reader("--json", env=env)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(message_fragment, completed.stderr)

    def test_no_environment_uses_versioned_defaults(self) -> None:
        """A missing config reader or wrong YAML default must break this test."""
        self.assertEqual(
            self.read_json(),
            {
                "BONSAI_FAMILY": "bonsai",
                "BONSAI_LLAMA_HOST": "0.0.0.0",
                "BONSAI_LLAMA_PORT": "8080",
                "BONSAI_MLX_PORT": "8081",
                "BONSAI_MODEL": "8B",
                "BONSAI_OPENWEBUI_MAX_PORT": "9099",
                "BONSAI_OPENWEBUI_PORT": "9090",
            },
        )

    def test_nonempty_environment_values_override_yaml_defaults(self) -> None:
        """A merge that ignores an explicit user override must break this test."""
        values = self.read_json(
            {
                "BONSAI_FAMILY": "ternary",
                "BONSAI_MODEL": "4B",
                "BONSAI_LLAMA_HOST": "127.0.0.1",
                "BONSAI_LLAMA_PORT": "18080",
                "BONSAI_MLX_PORT": "18081",
                "BONSAI_OPENWEBUI_PORT": "19090",
                "BONSAI_OPENWEBUI_MAX_PORT": "19099",
            }
        )
        self.assertEqual(values["BONSAI_FAMILY"], "ternary")
        self.assertEqual(values["BONSAI_MODEL"], "4B")
        self.assertEqual(values["BONSAI_LLAMA_HOST"], "127.0.0.1")
        self.assertEqual(values["BONSAI_LLAMA_PORT"], "18080")
        self.assertEqual(values["BONSAI_MLX_PORT"], "18081")
        self.assertEqual(values["BONSAI_OPENWEBUI_PORT"], "19090")
        self.assertEqual(values["BONSAI_OPENWEBUI_MAX_PORT"], "19099")

    def test_shell_mode_exports_effective_values(self) -> None:
        """Unsafe or incomplete shell output must break an actual POSIX shell consumer."""
        command = 'eval "$(python3 "$1" --shell)"; printf "%s/%s/%s" "$BONSAI_FAMILY" "$BONSAI_MODEL" "$BONSAI_LLAMA_PORT"'
        completed = subprocess.run(
            ["sh", "-c", command, "sh", str(READER)],
            cwd=REPOSITORY,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "bonsai/8B/8080")

    def test_sourcing_common_exports_canonical_server_defaults(self) -> None:
        """A common.sh that retains port defaults or skips the reader must break this test."""
        command_env = os.environ.copy()
        for name in RUNTIME_ENV_NAMES:
            command_env.pop(name, None)
        completed = subprocess.run(
            [
                "sh",
                "-c",
                '. scripts/common.sh; printf "%s/%s/%s/%s" "$BONSAI_FAMILY" "$BONSAI_MODEL" "$BONSAI_LLAMA_PORT" "$BONSAI_OPENWEBUI_PORT"',
            ],
            cwd=REPOSITORY,
            env=command_env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "bonsai/8B/8080/9090")

    def test_common_honors_unexported_shell_override(self) -> None:
        """A subprocess-only reader must not discard a caller's explicit shell value."""
        command_env = os.environ.copy()
        for name in RUNTIME_ENV_NAMES:
            command_env.pop(name, None)
        completed = subprocess.run(
            [
                "sh",
                "-c",
                'BONSAI_FAMILY=ternary; BONSAI_MODEL=4B; . scripts/common.sh; printf "%s/%s" "$BONSAI_FAMILY" "$BONSAI_MODEL"',
            ],
            cwd=REPOSITORY,
            env=command_env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ternary/4B")

    def test_mlx_generator_validates_canonical_configuration_before_loading_model(self) -> None:
        """A generator bypassing the reader would fail to reject an invalid port."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            fake_modules = Path(temporary_directory)
            (fake_modules / "mlx").mkdir()
            (fake_modules / "mlx_lm").mkdir()
            (fake_modules / "mlx" / "__init__.py").write_text("", encoding="utf-8")
            (fake_modules / "mlx" / "core.py").write_text("", encoding="utf-8")
            (fake_modules / "mlx_lm" / "__init__.py").write_text(
                "def load(*args): pass\ndef stream_generate(*args): return ()\n", encoding="utf-8"
            )
            (fake_modules / "mlx_lm" / "generate.py").write_text(
                "def make_sampler(*args): pass\n", encoding="utf-8"
            )
            command_env = os.environ.copy()
            for name in RUNTIME_ENV_NAMES:
                command_env.pop(name, None)
            command_env["BONSAI_LLAMA_PORT"] = "70000"
            command_env["PYTHONPATH"] = str(fake_modules)
            completed = subprocess.run(
                ["python3", "scripts/mlx_generate.py", "--help"],
                cwd=REPOSITORY,
                env=command_env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("BONSAI_LLAMA_PORT", completed.stderr)

    def test_invalid_model_is_rejected(self) -> None:
        self.assert_config_error({"BONSAI_MODEL": "16B"}, "BONSAI_MODEL")

    def test_invalid_family_is_rejected(self) -> None:
        self.assert_config_error({"BONSAI_FAMILY": "unsupported"}, "BONSAI_FAMILY")

    def test_invalid_port_is_rejected(self) -> None:
        self.assert_config_error({"BONSAI_LLAMA_PORT": "70000"}, "BONSAI_LLAMA_PORT")

    def test_openwebui_port_range_is_validated(self) -> None:
        self.assert_config_error(
            {
                "BONSAI_OPENWEBUI_PORT": "19099",
                "BONSAI_OPENWEBUI_MAX_PORT": "19090",
            },
            "BONSAI_OPENWEBUI_MAX_PORT",
        )

    def test_openwebui_port_range_cannot_contain_backend_port(self) -> None:
        self.assert_config_error(
            {
                "BONSAI_OPENWEBUI_PORT": "18080",
                "BONSAI_OPENWEBUI_MAX_PORT": "18082",
                "BONSAI_LLAMA_PORT": "18081",
            },
            "BONSAI_OPENWEBUI_PORT range",
        )


if __name__ == "__main__":
    unittest.main()
