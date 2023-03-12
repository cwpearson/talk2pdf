import sys
import subprocess
from datetime import datetime
from pathlib import Path
import argparse
import hashlib
import struct
import difflib
from collections import namedtuple
import json

from pydub import AudioSegment, silence

import talk2pdf.utils as utils
import talk2pdf.config as config
import talk2pdf.t2p_openai as t2p_openai
import talk2pdf.t2p_whisper as t2p_whisper
import talk2pdf.t2p_ffmpeg as t2p_ffmpeg
import talk2pdf.ytdlp as ytdlp

Block = namedtuple("Block", ["text", "when", "image_path"])

TODAY_STRING = datetime.today().strftime('%b %d, %Y')
CHATGPT_MAX_STRING_LEN = 3000
OPENAI_AUDIO_LIMIT_BYTES = 1024 * 1024 * 25


def _chunk_path(digest, i):
    return config.get(config.KEY_CACHE_DIR) / f"{digest}-{i}.mp3"


def _detect_noise_with_backoff(audio, max_span_length):
    adj = 31
    while True:
        silences = silence.detect_silence(
            audio, min_silence_len=1000, silence_thresh=audio.dBFS-adj, seek_step=50)

        # noisy from 0 to the beginning of the first silence
        noise_spans = [(0, silences[0][0])]

        # noisy from end of each silence to the beginning of the next one
        for s1, s2 in zip(silences[0:-1], silences[1:]):
            noise_spans += [(s1[1], s2[0])]

        # noisy from end of final silence to the end of the audio
        noise_spans += [(silences[-1][1], len(audio))]

        # remove 0-length noisy spans
        new_spans = []
        for span in noise_spans:
            if span[1] - span[0] > 0:
                new_spans += [span]
        noise_spans = new_spans

        # check that no segment is longer than the size
        lengths = [span[1] - span[0] for span in noise_spans]

        # if any segments between silence are longer than the target length,
        # make silence less strict
        if any(map(lambda l: l > max_span_length, lengths)):
            adj -= 1
        else:
            break
    return noise_spans


def _combine_spans(spans, max_length):
    # recombine noise_spans but keep less than MAX_AUDIO_CHUNK_MS
    changed = True
    while changed:
        changed = False

        # find the split that produces the largest segment less than MAX_AUDIO_CHUNK_MS
        largest = None
        si = None

        for i, (s1, s2) in enumerate(zip(spans[:-1], spans[1:])):
            combined_length = s2[1] - s1[0]

            if combined_length <= max_length:
                if largest is None or combined_length > largest:
                    largest = combined_length
                    si = i

        if largest is not None:
            new_spans = spans[:si]
            new_spans += [(spans[si][0], spans[si+1][1])]
            new_spans += spans[si+2:]
            spans = new_spans
            changed = True
    return spans


def _export_spans(audio, spans, seed):
    paths = []
    for span in spans:

        # generate unique filename for each span
        h = hashlib.md5()
        h.update(seed.encode('utf-8'))
        h.update(bytearray(struct.pack("f", span[0])))
        h.update(bytearray(struct.pack("f", span[1])))
        path = config.get(config.KEY_CACHE_DIR) / (h.hexdigest() + ".mp3")

        if not path.is_file():
            utils.eprint(f"==== write {path} for {span[0],span[1]}")
            c = audio[span[0]:span[1]]
            c.export(path)
        paths += [path]
    return paths


def _transcribe_files(paths, at_sandia):
    transcripts = []
    for path in paths:

        utils.eprint(f"==== transcribe {path}")

        method = config.get(config.KEY_TRANSCRIBE)
        if method == config.TRANSCRIBE_OPENAI_WHISPER:
            transcript = t2p_whisper.transcribe(path)
        elif method == config.TRANSCRIBE_OPENAI:
            if at_sandia:
                utils.set_requests_ca_bundle()
            transcript = t2p_openai.transcribe(path)
        else:
            raise RuntimeError(f"unsupported transcribe method {method}")
        transcripts += [transcript]

    return transcripts


def _combine_segments(segments, max_length):
    chunk = ""
    chunks = []
    for seg in segments:
        if len(chunk) + len(seg["text"]) < CHATGPT_MAX_STRING_LEN:
            chunk += seg["text"]
        else:  # save chunk and start a new one
            chunks += [chunk.strip()]
            chunk = ""
    if chunk != "":
        chunks += [chunk.strip()]
    return chunks


def _clean_texts(texts, at_sandia):

    cleans = []
    for text in texts:
        # continuing an incomplete line seems to make ChatGPT hallucinate
        text = text.strip()
        if text[-1] not in ".!?":
            text += "."
        text + "\n\n"

        if at_sandia:
            utils.set_requests_ca_bundle()
        cleans += [t2p_openai.clean(text)]
    return cleans


def _do_video_file(video_path, title, at_sandia, url=None):

    utils.eprint(
        f"==== cache dir size is {config.cache_dir_size() / 1024 / 1024:.2f} MiB")

    video_digest = utils.hash_file(video_path)
    utils.eprint(f"==== video digest: {video_digest}")

    audio_path = config.get(config.KEY_CACHE_DIR) / f"{video_digest}.mp3"
    t2p_ffmpeg.extract_audio(audio_path, video_path)

    utils.eprint(f"==== load {audio_path}")
    if audio_path.suffix == ".mp3":
        full_segment = AudioSegment.from_mp3(audio_path)
    else:
        utils.eprint(f"unsupported audio file {audio_path}")
        sys.exit(1)

    audio_size = audio_path.stat().st_size
    audio_time = len(full_segment) / 1000.0

    utils.eprint(
        f"==== {audio_path} is {audio_size/1024.0/1024.4:.2f} MiB / {audio_time:.2f}s")

    bytes_per_second = audio_size / audio_time

    seconds_for_openai_limit = OPENAI_AUDIO_LIMIT_BYTES / bytes_per_second
    seconds_for_openai_limit *= 0.9  # fudge to make sure we're under the limit
    utils.eprint(f"==== estimate {seconds_for_openai_limit}s per audio chunk")
    ms_for_openai_limit = seconds_for_openai_limit * 1000

    noise_spans = _detect_noise_with_backoff(full_segment, ms_for_openai_limit)
    utils.eprint(f"==== {len(noise_spans)} raw noisy spans")

    noise_spans = _combine_spans(noise_spans, ms_for_openai_limit)
    utils.eprint(f"==== combined to {len(noise_spans)} audio spans")

    noise_paths = _export_spans(full_segment, noise_spans, video_digest)
    assert len(noise_paths) == len(noise_spans)

    transcripts = _transcribe_files(noise_paths, at_sandia)

    full_transcript = {"segments": []}
    assert len(noise_spans) == len(transcripts)
    for transcript, span in zip(transcripts, noise_spans):
        for seg in transcript["segments"]:
            full_transcript["segments"] += [{
                "text": seg["text"],
                "start": seg["start"] + span[0] / 1000.0,
            }]

    chunks = _combine_segments(
        full_transcript["segments"], CHATGPT_MAX_STRING_LEN)

    clean_chunks = _clean_texts(chunks, at_sandia)

    # each chunk may have multiple paragraphs in it
    blocks = []
    for chunk in clean_chunks:
        for paragraph in chunk.split("\n\n"):
            blocks += [Block(paragraph, None, None)]

    utils.eprint(f'==== {len(blocks)} blocks')

    # Find a timestamp for the beginning of each paragraph
    # Do this by comparing the beginning of the paragraph to each segment
    # When we find the matching segment, we have a timestamp for the beginning of the paragraph
    later_than = -1
    blocks_with_starts = []
    for block in blocks:

        # find the first segment after no_earlier_than which matches the paragraph
        found = False
        for seg in full_transcript["segments"]:
            if seg["start"] < later_than:
                continue

            # compare the beginning of p and seg["text"],
            # consider seg["text"] to be the beginning of p if the match is close

            s = difflib.SequenceMatcher(
                lambda c: 0, block.text[:len(seg["text"])], seg["text"])
            if s.ratio() > 0.8:
                when = float(seg["start"])
                later_than = when
                utils.eprint(
                    f'======== matched "{block.text[:25]}... to {seg["text"][:25]}..." at {when:.2f}s (score={s.ratio():.2f})')
                blocks_with_starts += [Block(block.text, when, None)]
                found = True
                break

        if not found:
            # couldn't find a timestamp for this paragraph
            blocks_with_starts += [Block(block.text, None, None)]
            utils.eprint(
                f"======== WARN: couldn't find any segments in {block.text}!")
            sys.exit(1)

    md_path = config.get(config.KEY_CACHE_DIR) / f"{video_digest}.md"
    pdf_path = f"{video_digest}.pdf"

    blocks_with_images = []
    for bi, block in enumerate(blocks_with_starts):

        # This block has a time, so extract an image
        if block.when is not None:
            frame_path = t2p_ffmpeg.extract_frame(
                config.get(config.KEY_CACHE_DIR), video_path, block.when)

            # only include this image if it's different enough from
            # an image in a previous block, or it's the first block
            if bi == 0:
                blocks_with_images += [Block(block.text,
                                             block.when, frame_path)]
                recent_frame_path = frame_path
            elif not utils.is_same_image(frame_path, recent_frame_path):
                blocks_with_images += [
                    Block(block.text, block.when, frame_path)]
                recent_frame_path = frame_path
                utils.eprint(
                    f"==== image for block {bi} is new")
            else:
                # no image to include, it's the same as the most recent image
                blocks_with_images += [block]
        else:
            # don't know when this block is, can't add an image
            blocks_with_images += [block]

    # write document header
    with open(md_path, 'w') as f:

        f.write(f"""---
title: "{title}"
author: talk2pdf (by Carl Pearson)
date: {TODAY_STRING}
geometry: "left=2cm,right=2cm,top=2cm,bottom=2cm"
output: pdf_document
"""
                )

        # add headers, disable floats to keep screenshots near next
        f.write(r"""header-includes: |
    \usepackage{fancyhdr}
    \pagestyle{fancy}
    \fancyhead[CO,CE]{Made with github.com/cwpearson/talk2pdf}
    \fancyfoot[CO,CE]{Made with github.com/cwpearson/talk2pdf}
    \fancyfoot[LE,RO]{\thepage}
    \usepackage{float}
    \let\origfigure\figure
    \let\endorigfigure\endfigure
    \renewenvironment{figure}[1][2] {
        \expandafter\origfigure\expandafter[H]
    } {
        \endorigfigure
    }
---
""")

        for block in blocks_with_images:

            if block.when is None:
                caption = ""
            else:
                hh, ss = divmod(block.when, 3600)
                mm, ss = divmod(ss, 60)
                hh = int(hh)
                mm = int(mm)
                ss = int(ss)
                caption = f"[{hh}h{mm}m{ss}s]({url}&t={hh}h{mm}m{ss}s)"

            if frame_path is not None:
                f.write(r"""```{=latex}
\begin{center}
```
""")
                f.write(f'![{caption}]({frame_path})')
                f.write(r"{width=50% margin=auto}")
                f.write(r"""
```{=latex}
\end{center}
```
""")
                f.write("\n\n")
            f.write(block.text)
            f.write("\n\n")

    # cmd = ['pandoc', '-f', 'markdown-implicit_figures',
    #        '-i', md_path, '-o', pdf_path]
    cmd = ['pandoc', '-f', 'markdown',
           '-i', md_path, '-o', pdf_path]
    utils.eprint(f'==== {" ".join(map(str, cmd))}')
    subprocess.run(cmd)

    utils.eprint(f"==== wrote to {pdf_path}")


def _do_youtube(url):
    title = ytdlp.get_title(url)
    utils.eprint(f"==== title is {title}")

    cache_dir = config.get(config.KEY_CACHE_DIR)
    utils.eprint(f"==== ensure {cache_dir}")
    cache_dir.mkdir(parents=True, exist_ok=True)

    video_path = ytdlp.download(url, cache_dir)
    _do_video_file(video_path, title, utils.at_sandia(), url=url)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        prog="talk2pdf",
        description="Convert recorded talks to PDFs",
        epilog="By Carl Pearson -- https://github.com/cwpearson/talk2pdf"
    )

    parser.add_argument('URI', help="A video file or URL")
    parser.add_argument(
        '-t', '--title', help="The title to use in the output PDF")

    args = parser.parse_args()
    config.load()

    if not config.config_file().is_file():
        utils.eprint(f"==== writing default config to {config.config_file()}")
        config.config_dir().mkdir(parents=True, exist_ok=True)
        with open(config.config_file(), 'w') as f:
            f.write(json.dumps(config.default_config()))

    if not args.title:
        title = f'talk2pdf transcription of {args.URI}'
    else:
        title = args.title

    if "youtube.com/watch" in args.URI:
        _do_youtube(args.URI)
    elif Path(args.URL).is_file():
        _do_video_file(Path(args.URI), title, utils.at_sandia())
    else:
        utils.eprint("expected Youtube URL or video file path")
