import os
from pathlib import Path
import json
import sys
from enum import Enum

import talk2pdf.utils as utils


KEY_TRANSCRIBE = "transcribe"
KEY_OPENAI_SECRET = "openapi_secret"
KEY_CACHE_DIR = "cache_dir"

TRANSCRIBE_OPENAI_WHISPER = "openai_whisper"
TRANSCRIBE_OPENAI = "openai"


class Config(object):
    def __init__(self, raw):
        self.raw = raw

    def __getitem__(self, k):
        return self.raw[k]


_singleton = Config({})


def config_dir():
    if "TALK2PDF_CONFIG_DIR" in os.environ:
        return Path(os.environ["TALK2PDF_CONFIG_DIR"])
    elif "XDG_CONFIG_HOME" in os.environ:
        return Path(os.environ["XDG_CONFIG_HOME"]) / "talk2pdf"
    else:
        return Path(os.environ["HOME"]) / ".config" / "talk2pdf"


def config_file():
    return config_dir() / "config.json"


def default_config():
    return {
        KEY_TRANSCRIBE: TRANSCRIBE_OPENAI_WHISPER,
        KEY_OPENAI_SECRET: "",
    }


def load():
    config_dir().mkdir(parents=True, exist_ok=True)
    if not config_file().is_file():
        with open(config_file(), 'w') as f:
            f.write(json.dumps(default_config()))

    d = {}
    d[KEY_CACHE_DIR] = _cache_dir()
    d[KEY_OPENAI_SECRET] = _openapi_secret()
    d[KEY_TRANSCRIBE] = _transcribe()
    global _singleton
    _singleton = Config(d)


def _openapi_secret():
    if "OPENAPI_SECRET" in os.environ:
        return os.environ["OPENAPI_SECRET"]
    elif config_file().is_file():
        with open(config_file(), 'r') as f:
            return json.loads(f.read())[KEY_OPENAI_SECRET]
    else:
        print(
            f'please set environment "OPENAPI_SECRET" to your OpenAI secret key or {KEY_OPENAI_SECRET} in {config_file}')
        sys.exit(1)


def _cache_dir():
    if "TALK2PDF_CACHE_DIR" in os.environ:
        return Path(os.environ["TALK2PDF_CACHE_DIR"])
    elif "XDG_CACHE_HOME" in os.environ:
        return Path(os.environ["XDG_CACHE_HOME"]) / "talk2pdf"
    else:
        with open(config_file(), 'r') as f:
            j = json.loads(f.read())
            if KEY_CACHE_DIR in j:
                return j[KEY_CACHE_DIR]
    return Path(os.environ["HOME"]) / ".cache" / "talk2pdf"


def _transcribe():
    with open(config_file(), 'r') as f:
        return json.loads(f.read())[KEY_TRANSCRIBE]


def cache_dir_size():
    def dir_size(path):
        acc = 0
        for f in path.glob("**/*"):
            if f.is_file():
                acc += f.stat().st_size
            elif f.is_dir():
                acc += dir_size(f)
        return acc

    return dir_size(_cache_dir())


def get(k):
    return _singleton[k]
