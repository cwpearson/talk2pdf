import subprocess
import os
import sys
import hashlib

from PIL import Image
import imagehash


def eprint(*args, **kwargs):
    kwargs["file"] = sys.stderr
    print(" ".join(map(str, args)), **kwargs)


def at_sandia():
    cp = subprocess.run(['ping', '-c', '1', '-t', '1',
                        'inside.sandia.gov'], capture_output=True)
    if cp.returncode != 0:
        eprint("==== not at Sandia (ping failed)")
        return False
    eprint("==== at Sandia (ping succeeded)")
    return True


def set_requests_ca_bundle():
    _DEFAULT = os.environ["HOME"] + \
        "/Downloads/sandia_certificate/sandia_root_ca.cer"
    if "REQUESTS_CA_BUNDLE" not in os.environ:
        eprint(f"==== set REQUESTS_CA_BUNDLE to {_DEFAULT}")
        os.environ["REQUESTS_CA_BUNDLE"] = _DEFAULT


def clear_sandia_proxies():
    vars = ["https_proxy", "http_proxy"]
    env = {}
    for var in vars:
        if var in os.environ:
            env[var] = os.environ[var]
            eprint(f"==== clear {var} (was {env[var]})")
            del os.environ[var]
    return env


def restore_sandia_proxies(env):
    for k, v in env.items:
        eprint(f"==== restore {k}={v}")
        if v is None and k in os.environ:
            del os.environ[k]
        else:
            os.environ[k] = v


def paste():
    cp = subprocess.run(['pbpaste'], capture_output=True)
    return cp.stdout.decode('utf-8')


def copy(string):
    cp = subprocess.run(['pbcopy'], input=string.encode('utf-8'))
    return cp.returncode == 0


def hash_file(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def is_same_image(path1, path2):
    hash0 = imagehash.dhash(Image.open(path1))
    hash1 = imagehash.dhash(Image.open(path2))

    # some small deviation still considered the same
    # because some small motion usually in frame (presenter moving)
    return (hash1 - hash0) <= 1

def pandoc_frontmatter_safe(text):
    return text