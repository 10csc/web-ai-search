# -*- coding: utf-8 -*-
"""Runtime path ownership.

Code lives in the skill directory. Mutable runtime state belongs in a user
runtime directory so the skill can be upgraded or called by different hosts
without mixing code, config, logs, and learned profiles.
"""

import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)


def _default_runtime_home():
    override = os.environ.get("WEBAISEARCH_HOME", "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return os.path.join(local_app_data, "WebAISearch")

    return os.path.join(os.path.expanduser("~"), ".web-ai-search")


RUNTIME_HOME = _default_runtime_home()
CONFIG_PATH = os.path.join(RUNTIME_HOME, "config.json")
DATA_DIR = os.path.join(RUNTIME_HOME, "data")
WORKSPACE_DIR = os.path.join(DATA_DIR, "workspace")
MEMORY_DIR = os.path.join(DATA_DIR, "memory")
PROFILES_DIR = os.path.join(RUNTIME_HOME, "profiles")


def ensure_runtime_dirs():
    for path in (RUNTIME_HOME, DATA_DIR, WORKSPACE_DIR, MEMORY_DIR, PROFILES_DIR):
        os.makedirs(path, exist_ok=True)


def legacy_config_path():
    return os.path.join(SKILL_DIR, "config.json")


def resolve_config_path():
    if os.path.exists(CONFIG_PATH):
        return CONFIG_PATH
    legacy = legacy_config_path()
    if os.path.exists(legacy):
        return legacy
    ensure_runtime_dirs()
    return CONFIG_PATH
