import requests
import sys
import json
import hashlib

import whisper

from talk2pdf import config
from talk2pdf import utils

_MODEL = "base.en"


def ensure_model():
    whisper.load_model(_MODEL)


def transcribe(path):

    h = hashlib.md5()
    h.update(_MODEL.encode('utf-8'))
    with open(path, 'rb') as f:
        h.update(f.read())
    digest = h.hexdigest()

    cache_path = config.get(config.KEY_CACHE_DIR) / f"{digest}.json"

    if cache_path.is_file():
        utils.eprint(f"==== reading cached {cache_path}")
        with open(cache_path, "r") as f:
            result = json.loads(f.read())
    else:
        model = whisper.load_model("base.en")
        result = model.transcribe(str(path), verbose=True)
        utils.eprint(f"==== caching response @ {cache_path}")
        with open(cache_path, 'w') as f:
            f.write(json.dumps(result))
    return result


if __name__ == "__main__":
    transcribe(sys.argv[1])
