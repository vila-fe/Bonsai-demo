#!/usr/bin/env python3
"""Load, validate, and export the Bonsai runtime configuration.

The repository intentionally avoids a YAML dependency for a small, stable runtime
configuration.  The parser accepts only the plain-scalar, two-space-indented map
shape used by config/runtime.yaml and fails closed for other YAML constructs.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Mapping


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "runtime.yaml"
VALID_FAMILIES = frozenset(("bonsai", "ternary", "all"))
VALID_MODELS = frozenset(("8B", "4B", "1.7B", "all"))
KEY_PATTERN = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9_-]*):(?: (?P<value>.*))?$")
ENVIRONMENT_PATHS = {
    "BONSAI_FAMILY": ("model", "family"),
    "BONSAI_MODEL": ("model", "size"),
    "BONSAI_LLAMA_HOST": ("server", "llama", "host"),
    "BONSAI_LLAMA_PORT": ("server", "llama", "port"),
    "BONSAI_MLX_PORT": ("server", "mlx", "port"),
    "BONSAI_OPENWEBUI_PORT": ("server", "openwebui", "port"),
    "BONSAI_OPENWEBUI_MAX_PORT": ("server", "openwebui", "max_port"),
}


class RuntimeConfigError(ValueError):
    """Raised when the committed configuration or effective environment is invalid."""


def parse_plain_yaml_mapping(path: Path) -> dict[str, object]:
    """Parse the intentionally small YAML mapping subset used by runtime.yaml."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise RuntimeConfigError(f"cannot read runtime config {path}: {error}") from error

    root: dict[str, object] = {}
    stack: list[tuple[int, dict[str, object]]] = [(-1, root)]
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if "\t" in raw_line:
            raise RuntimeConfigError(f"{path}:{line_number}: tabs are not supported")

        indentation = len(raw_line) - len(raw_line.lstrip(" "))
        if indentation % 2:
            raise RuntimeConfigError(f"{path}:{line_number}: indentation must use two spaces")
        content = raw_line[indentation:]
        match = KEY_PATTERN.fullmatch(content)
        if not match:
            raise RuntimeConfigError(
                f"{path}:{line_number}: expected a plain YAML key and scalar value"
            )

        while stack[-1][0] >= indentation:
            stack.pop()
        parent_indentation, parent = stack[-1]
        expected_indentation = 0 if parent_indentation == -1 else parent_indentation + 2
        if indentation != expected_indentation:
            raise RuntimeConfigError(
                f"{path}:{line_number}: unexpected indentation for key {match['key']!r}"
            )

        key = match["key"]
        if key in parent:
            raise RuntimeConfigError(f"{path}:{line_number}: duplicate key {key!r}")
        value = match["value"]
        if value is None:
            child: dict[str, object] = {}
            parent[key] = child
            stack.append((indentation, child))
            continue
        if not value or value != value.strip() or value.startswith(("'", '"')):
            raise RuntimeConfigError(
                f"{path}:{line_number}: values must be non-empty unquoted plain scalars"
            )
        if any(character in value for character in "#[]{}&,*!|>'\""):
            raise RuntimeConfigError(
                f"{path}:{line_number}: unsupported YAML syntax in value for {key!r}"
            )
        parent[key] = value

    return root


def _require_mapping(parent: Mapping[str, object], key: str, location: str) -> Mapping[str, object]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise RuntimeConfigError(f"{location}.{key} must be a mapping")
    return value


def _require_exact_keys(mapping: Mapping[str, object], expected: set[str], location: str) -> None:
    actual = set(mapping)
    if actual != expected:
        missing = ", ".join(sorted(expected - actual)) or "none"
        unexpected = ", ".join(sorted(actual - expected)) or "none"
        raise RuntimeConfigError(
            f"{location} keys must be {', '.join(sorted(expected))}; "
            f"missing: {missing}; unexpected: {unexpected}"
        )


def _require_scalar(parent: Mapping[str, object], key: str, location: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str):
        raise RuntimeConfigError(f"{location}.{key} must be a non-empty plain scalar")
    return value


def _config_value(config: Mapping[str, object], path: tuple[str, ...]) -> str:
    current: Mapping[str, object] = config
    location = "runtime"
    for key in path[:-1]:
        current = _require_mapping(current, key, location)
        location = f"{location}.{key}"
    return _require_scalar(current, path[-1], location)


def _validate_port(name: str, value: str) -> int:
    if not value.isdecimal():
        raise RuntimeConfigError(f"{name} must be an integer between 1 and 65535, got {value!r}")
    port = int(value)
    if not 1 <= port <= 65535:
        raise RuntimeConfigError(f"{name} must be an integer between 1 and 65535, got {value!r}")
    return port


def validate_config_shape(config: Mapping[str, object]) -> None:
    """Reject missing or unknown fields so typoed defaults never silently apply."""
    _require_exact_keys(config, {"model", "server"}, "runtime")
    model = _require_mapping(config, "model", "runtime")
    _require_exact_keys(model, {"family", "size"}, "runtime.model")
    _require_scalar(model, "family", "runtime.model")
    _require_scalar(model, "size", "runtime.model")

    server = _require_mapping(config, "server", "runtime")
    _require_exact_keys(server, {"llama", "mlx", "openwebui"}, "runtime.server")
    llama = _require_mapping(server, "llama", "runtime.server")
    _require_exact_keys(llama, {"host", "port"}, "runtime.server.llama")
    _require_scalar(llama, "host", "runtime.server.llama")
    _require_scalar(llama, "port", "runtime.server.llama")
    mlx = _require_mapping(server, "mlx", "runtime.server")
    _require_exact_keys(mlx, {"port"}, "runtime.server.mlx")
    _require_scalar(mlx, "port", "runtime.server.mlx")
    openwebui = _require_mapping(server, "openwebui", "runtime.server")
    _require_exact_keys(openwebui, {"port", "max_port"}, "runtime.server.openwebui")
    _require_scalar(openwebui, "port", "runtime.server.openwebui")
    _require_scalar(openwebui, "max_port", "runtime.server.openwebui")


def load_effective_config(path: Path, environment: Mapping[str, str]) -> dict[str, str]:
    """Load committed defaults, apply non-empty environment overrides, and validate."""
    config = parse_plain_yaml_mapping(path)
    validate_config_shape(config)
    values = {
        environment_name: environment.get(environment_name) or _config_value(config, config_path)
        for environment_name, config_path in ENVIRONMENT_PATHS.items()
    }

    if values["BONSAI_FAMILY"] not in VALID_FAMILIES:
        raise RuntimeConfigError(
            "BONSAI_FAMILY must be one of: bonsai, ternary, all; "
            f"got {values['BONSAI_FAMILY']!r}"
        )
    if values["BONSAI_MODEL"] not in VALID_MODELS:
        raise RuntimeConfigError(
            "BONSAI_MODEL must be one of: 8B, 4B, 1.7B, all; "
            f"got {values['BONSAI_MODEL']!r}"
        )

    host = values["BONSAI_LLAMA_HOST"]
    if host != "localhost":
        try:
            ipaddress.ip_address(host)
        except ValueError as error:
            raise RuntimeConfigError(
                "BONSAI_LLAMA_HOST must be localhost or an IPv4/IPv6 address; "
                f"got {host!r}"
            ) from error

    ports = {
        name: _validate_port(name, values[name])
        for name in (
            "BONSAI_LLAMA_PORT",
            "BONSAI_MLX_PORT",
            "BONSAI_OPENWEBUI_PORT",
            "BONSAI_OPENWEBUI_MAX_PORT",
        )
    }
    if ports["BONSAI_OPENWEBUI_MAX_PORT"] < ports["BONSAI_OPENWEBUI_PORT"]:
        raise RuntimeConfigError(
            "BONSAI_OPENWEBUI_MAX_PORT must be greater than or equal to "
            "BONSAI_OPENWEBUI_PORT"
        )
    endpoint_ports = (
        ports["BONSAI_LLAMA_PORT"],
        ports["BONSAI_MLX_PORT"],
        ports["BONSAI_OPENWEBUI_PORT"],
    )
    if len(set(endpoint_ports)) != len(endpoint_ports):
        raise RuntimeConfigError(
            "BONSAI_LLAMA_PORT, BONSAI_MLX_PORT, and BONSAI_OPENWEBUI_PORT must differ"
        )

    return values


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="path to the restricted YAML runtime configuration (default: %(default)s)",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="print effective values as JSON")
    output.add_argument("--shell", action="store_true", help="print safely quoted POSIX shell exports")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        values = load_effective_config(arguments.config, os.environ)
    except RuntimeConfigError as error:
        print(f"runtime configuration error: {error}", file=sys.stderr)
        return 1

    if arguments.json:
        print(json.dumps(values, sort_keys=True))
    else:
        for name, value in values.items():
            print(f"export {name}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
