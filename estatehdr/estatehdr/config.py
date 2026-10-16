"""Configuration: one YAML file (config.yaml) with defaults + presets.

Resolution order (later wins):
  1. built-in config.yaml;
  2. the user file's ``presets`` section, merged into the built-in presets;
  3. overrides of the selected preset;
  4. user-file values that *differ from the built-in defaults* (a recursive diff, ``presets``
     excluded): a full copy of config.yaml with a few edits applies only those edits and does
     not undo the preset, while a calibrated / custom file wins over every preset;
  5. command-line ``--set section.key=value`` overrides (the value is parsed as YAML) and
     ``(section.key, value)`` tuples, set as they are (CLI flag values such as file paths).
Mode switches documented as ``auto | off`` are read with ``mode_of`` (YAML turns ``off`` into False).
"""
from __future__ import annotations

import copy
import os
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


class ConfigError(ValueError):
    """Bad configuration input (config file, preset name, override); ``pl``: the message for the
    (Polish) command line."""

    def __init__(self, msg: str, pl: str):
        super().__init__(msg)
        self.pl = pl


class Config(dict):
    """dict with attribute access for nested sections (read-only convenience)."""

    def __getattr__(self, item):
        try:
            v = self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc
        return Config(v) if isinstance(v, dict) and not isinstance(v, Config) else v

    def section(self, name: str) -> "Config":
        return Config(self.get(name, {}) or {})


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


_MISSING = object()
_OFF = {"off", "false", "none", "no", "0", "disabled"}


def mode_of(v: Any, default: str = "auto") -> str:
    """Normalised mode switch: False / None / "off" / "false" / "none" / "no" / 0 -> "off";
    True / "on" / "yes" -> ``default``; anything else -> its lower-case string."""
    if v is None or v is False:
        return "off"
    if v is True:
        return default
    s = str(v).strip().lower()
    if s in _OFF:
        return "off"
    if s in ("", "on", "true", "yes"):
        return default
    return s


def diff_from(user: dict, base: dict) -> dict:
    """Entries of ``user`` whose values differ from ``base`` (recursively)."""
    out = {}
    for k, v in (user or {}).items():
        b = base.get(k, _MISSING) if isinstance(base, dict) else _MISSING
        if isinstance(v, dict) and isinstance(b, dict):
            d = diff_from(v, b)
            if d:
                out[k] = d
        elif b is _MISSING or v != b:
            out[k] = copy.deepcopy(v)
    return out


def _parse_value(s: str) -> Any:
    try:
        return yaml.safe_load(s)
    except yaml.YAMLError:
        return s


def set_path(d: dict, dotted: str, value: Any):
    keys = dotted.split(".")
    cur = d
    for k in keys[:-1]:
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def _read_user_file(path: str) -> dict:
    if not os.path.isfile(path):
        raise ConfigError(f"config file not found: {path}", f"nie ma pliku konfiguracji: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            user = yaml.safe_load(fh)
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}",
                          f"nie można odczytać pliku konfiguracji {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        what = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        en, pl = (f", line {mark.line + 1}", f", wiersz {mark.line + 1}") if mark is not None else ("", "")
        raise ConfigError(f"invalid YAML in {path}{en}: {what}",
                          f"błędny YAML w pliku konfiguracji {path}{pl}: {what}") from exc
    if not isinstance(user or {}, dict):
        raise ConfigError(f"config file {path} is not a YAML mapping",
                          f"plik konfiguracji {path} nie jest słownikiem YAML (sekcja: klucz: wartość)")
    return user or {}


def load_config(path: str | None = None, preset: str | None = None, overrides: list | None = None) -> Config:
    """``overrides``: ``"section.key=value"`` strings (value parsed as YAML) or ``(section.key, value)``
    tuples (value set as is).  Raises ``ConfigError`` for a missing / invalid file, an unknown preset
    or a malformed override."""
    with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as fh:
        base = yaml.safe_load(fh) or {}
    user = {}
    if path and os.path.abspath(path) != DEFAULT_CONFIG_PATH:
        user = _read_user_file(path)
    presets = deep_merge(base.get("presets") or {}, user.get("presets") or {})
    name = preset or user.get("preset") or base.get("preset", "neutral")
    if name not in presets:
        raise ConfigError(f"unknown preset '{name}', available: {', '.join(presets)}",
                          f"nieznany preset '{name}' (dostępne: {', '.join(presets)})")
    cfg = deep_merge(base, (presets[name] or {}).get("overrides", {}) or {})
    cfg["presets"] = presets
    edits = diff_from({k: v for k, v in user.items() if k != "presets"},
                      {k: v for k, v in base.items() if k != "presets"})
    cfg = deep_merge(cfg, edits)
    cfg["preset"] = name
    for item in overrides or []:
        k, v = "", None
        if isinstance(item, tuple):  # CLI flag values (file paths...): no YAML parsing
            k, v = item[0].strip(), copy.deepcopy(item[1])
        elif "=" in item:
            k, v = item.split("=", 1)
            k, v = k.strip(), _parse_value(v.strip())
        if not k or not all(p.strip() for p in k.split(".")):
            raise ConfigError(f"override must look like section.key=value, got '{item}'",
                              f"--set wymaga postaci sekcja.klucz=wartość, podano: '{item}'")
        set_path(cfg, k, v)
    return Config(cfg)


def preset_names(path: str | None = None) -> dict:
    with open(path or DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    return {k: v.get("label", k) for k, v in (cfg.get("presets") or {}).items()}
