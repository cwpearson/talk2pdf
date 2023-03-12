import subprocess
import hashlib

import talk2pdf.utils as utils


def is_available():
    cp = subprocess.run(["ffmpeg", "--help"], capture_output=True)
    return cp.returncode == 0


def extract_frame(output_dir, video_path, when_seconds):
    hh, when_seconds = divmod(when_seconds, 3600)
    mm, when_seconds = divmod(when_seconds, 60)

    hh = int(hh)
    mm = int(mm)
    ss = round(when_seconds, 2)

    when = f'{hh}:{mm}:{ss}'

    # hash inputs to get a unique frame name
    h = hashlib.md5()
    h.update(when.encode('utf-8'))
    h.update(video_path.name.encode('utf-8'))
    digest = h.hexdigest()

    # ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / (digest + ".jpg")

    if not output_path.is_file():
        # ffmpeg -y -ss 01:23:45 -i input -frames:v 1 -q:v 2 output.jpg
        utils.eprint(f"==== write frame to {output_path}")
        cmd = ['ffmpeg', '-y', '-ss', when, "-i", str(video_path),
               '-frames:v', '1', '-q:v', '1', str(output_path)]
        utils.eprint(f'==== {" ".join(cmd)}')
        cp = subprocess.run(cmd, capture_output=True)
        if cp.returncode != 0:
            utils.eprint(cp.stdout)
            utils.eprint(cp.stderr)
            raise RuntimeError("failed to extract frame")
    else:
        utils.eprint(f"==== read existing frame @ {output_path}")
    return output_path


def video_duration(video_path):
    # ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 input.mp4
    cp = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", video_path], capture_output=True)
    return float(cp.stdout.decode('utf-8').strip())


def audio_duration(audio_path):
    # ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 input.mp4
    cp = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", audio_path], capture_output=True)
    return float(cp.stdout.decode('utf-8').strip())


def extract_audio(output_path, video_path):

    if output_path.is_file():
        vdur = video_duration(video_path)
        if abs(audio_duration(output_path) - vdur) < (0.01 * vdur):
            utils.eprint(
                f"==== {output_path} is already the audio for {video_path}")
            return

    # ffmpeg -i input.mp4 -map 0:a output.mp3
    utils.eprint(f"==== extract audio to {output_path}")
    cmd = ['ffmpeg', '-y', '-i',
           str(video_path), '-map', '0:a', str(output_path)]
    utils.eprint(f"==== {' '.join(cmd)}")
    utils.eprint(f'{" ".join(cmd)}')
    cp = subprocess.run(cmd, capture_output=True)
    if cp.returncode != 0:
        utils.eprint(cp.stdout)
        utils.eprint(cp.stderr)
        raise RuntimeError("failed to extract audio")


_available = False
try:
    _available = is_available()
except:
    pass
if not _available:
    raise RuntimeError("please make sure ffmpeg is in your path")
