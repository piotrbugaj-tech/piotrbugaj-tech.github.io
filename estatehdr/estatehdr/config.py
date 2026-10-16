"""Configuration: one YAML file (config.yaml) with defaults + presets.

Resolution order: built-in config.yaml -> user config file -> preset overrides ->
command-line ``--set section.key=value`` overrides.
"""
from __future__ import annotations

import copy
import os
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")


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


def load_config(path: str | None = None, preset: str | None = None, overrides: list[str] | None = None) -> Config:
    with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    if path and os.path.abspath(path) != DEFAULT_CONFIG_PATH:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = deep_merge(cfg, yaml.safe_load(fh) or {})
    presets = cfg.get("presets", {}) or {}
    name = preset or cfg.get("preset", "neutral")
    if name not in presets:
        raise ValueError(f"unknown preset '{name}', available: {', '.join(presets)}")
    cfg = deep_merge(cfg, presets[name].get("overrides", {}) or {})
    cfg["preset"] = name
    for item in overrides or []:
        if "=" not in item:
            raise ValueError(f"override must look like section.key=value, got '{item}'")
        k, v = item.split("=", 1)
        set_path(cfg, k.strip(), _parse_value(v.strip()))
    return Config(cfg)


def preset_names(path: str | None = None) -> dict:
    with open(path or DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    return {k: v.get("label", k) for k, v in (cfg.get("presets") or {}).items()}
