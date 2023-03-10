import subprocess
import hashlib

import utils


def get_title(url):
    utils.eprint(f"==== get title for {url}...")
    cmd = ['yt-dlp', '--no-check-certificates', '--print', r'%(title)s', url]
    cp = subprocess.run(cmd, capture_output=True)
    if cp.returncode != 0:
        utils.eprint(cp.stderr)
        utils.eprint(cp.stdout)
        raise RuntimeError(f"unable to get title for {url}")
    else:
        return cp.stdout.decode('utf-8').strip()


def download(url, work_dir):

    digest = hashlib.md5(url.encode('utf-8')).hexdigest()

    for f in work_dir.glob(f"{digest}.*"):
        if ".webm" in f.name:
            utils.eprint(f"==== using already downloaded {f}")
            return f

    video_path = work_dir / (digest + r".%(ext)s")
    utils.eprint(f"==== download {url} to {video_path}")
    cmd = ['yt-dlp', '--no-check-certificates', url, '-o', video_path]
    cp = subprocess.run(cmd, cwd=work_dir)

    for f in work_dir.glob(f"{digest}.*"):
        return f
