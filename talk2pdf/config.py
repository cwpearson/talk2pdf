import os
from pathlib import Path
import json
import sys

import talk2pdf.utils as utils


def config_dir():
    if "TALK2PDF_CONFIG_DIR" in os.environ:
        return Path(os.environ["TALK2PDF_CONFIG_DIR"])
    elif "XDG_CONFIG_HOME" in os.environ:
        return Path(os.environ["XDG_CONFIG_HOME"]) / "talk2pdf"
    else:
        return Path(os.environ["HOME"]) / ".config" / "talk2pdf"


def config_file():
    return config_dir() / "config.json"


def openapi_secret():

    conf_path = config_file()
    if conf_path.is_file():
        with open(conf_path, 'r') as f:
            conf = json.loads(f.read())
            if "openapi_secret" in conf:
                return conf["openapi_secret"]
    else:
        utils.eprint(f"=== no {conf_path} when looking for openapi_secret")

    if "OPENAPI_SECRET" not in os.environ:
        print('please set "OPENAPI_SECRET" to your OpenAI secret key')
        sys.exit(1)
    return os.environ["OPENAPI_SECRET"]


def cache_dir():
    if "TALK2PDF_CACHE_DIR" in os.environ:
        return Path(os.environ["TALK2PDF_CACHE_DIR"])
    elif "XDG_CACHE_HOME" in os.environ:
        return Path(os.environ["XDG_CACHE_HOME"]) / "talk2pdf"
    else:
        return Path(os.environ["HOME"]) / ".cache" / "talk2pdf"


def cache_dir_size():

    def dir_size(path):
        acc = 0
        for f in path.glob("**/*"):
            if f.is_file():
                acc += f.stat().st_size
            elif f.is_dir():
                acc += dir_size(f)
        return acc

    return dir_size(cache_dir())


def as_json(show_secrets=False):
    out = {}
    out["cache_dir"] = cache_dir()
    if show_secrets:
        out["openapi_secret"] = openapi_secret()
    return out
