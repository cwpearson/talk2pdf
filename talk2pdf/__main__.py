import sys
import subprocess
from datetime import datetime
from pathlib import Path
import argparse
import hashlib
import struct

from pydub import AudioSegment, silence

import talk2pdf.utils as utils
import talk2pdf.config as config
import talk2pdf.openai_cache as openai_cache
import talk2pdf.ffmpeg as ffmpeg
import talk2pdf.ytdlp as ytdlp


TODAY_STRING = datetime.today().strftime('%b %d, %Y')
CHATGPT_MAX_STRING_LEN = 3000
OPENAI_AUDIO_LIMIT_BYTES = 1024 * 1024 * 25


def _chunk_path(digest, i):
    return config.cache_dir() / f"{digest}-{i}.mp3"


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
        path = config.cache_dir() / (h.hexdigest() + ".mp3")

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
        if at_sandia:
            utils.set_requests_ca_bundle()
        transcript = openai_cache.transcribe(path)

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
        cleans += [openai_cache.clean(text)]
    return cleans


def _do_video_file(video_path, title, at_sandia, url=None):

    utils.eprint(config.as_json(show_secrets=True))
    utils.eprint(
        f"==== cache dir size is {config.cache_dir_size() / 1024 / 1024:.2f} MiB")

    video_digest = utils.hash_file(video_path)
    utils.eprint(f"==== video digest: {video_digest}")

    audio_path = config.cache_dir() / f"{video_digest}.mp3"
    ffmpeg.extract_audio(audio_path, video_path)

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

    paragraphs = ("\n\n".join(clean_chunks)).split("\n\n")
    utils.eprint(f'==== {len(paragraphs)} paragraphs')

    later_than = -1
    rows = []

    for p in paragraphs:

        # find the first segment after no_earlier_than which matches the paragraph
        found = False
        for seg in full_transcript["segments"]:
            if seg["start"] < later_than:
                continue
            if p.find(seg["text"]) != -1:
                when = float(seg["start"])
                later_than = when
                utils.eprint(
                    f'======== found "{p[:30]}..." at {when:.2f}s')
                rows += [(p, when, None)]
                found = True
                break

        if not found:
            # couldn't find a timestamp for this paragraph
            rows += [(p, None, None)]
            utils.eprint(f"======== WARN: couldn't find any segments in {p}!")
            sys.exit(1)

    md_path = config.cache_dir() / f"{video_digest}.md"
    pdf_path = f"{video_digest}.pdf"

    for ri, row in enumerate(rows):

        if row[1] is not None:  # there is a timestamp for this row, so we can extract an image
            frame_path = ffmpeg.extract_frame(
                config.cache_dir(), video_path, row[1])

            if ri != 0:
                # compare with previous image

                for pi in range(ri-1, -1, -1):
                    if rows[pi][2] is not None:  # found previous image
                        if not utils.is_same_image(frame_path, rows[pi][2]):
                            # paragraph, when, image
                            h, s = divmod(row[1], 3600)
                            m, s = divmod(s, 60)
                            h = int(h)
                            m = int(m)
                            s = round(s)
                            caption = f"[{h}h{m}m{s}s]({url}&t={h}h{m}m{s}s)"
                            rows[ri] = row[0], caption, frame_path
                            utils.eprint(
                                f"==== image for paragraph {ri} different enough from {pi}")

                        # compared with last used image, no need to go back further
                        break
            else:
                rows[ri] = row[0], row[1], frame_path

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

        for ri, row in enumerate(rows):

            paragraph = row[0]
            caption = row[1]
            frame_path = row[2]

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
            f.write(paragraph)
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

    utils.eprint(f"==== ensure {config.cache_dir()}")
    config.cache_dir().mkdir(parents=True, exist_ok=True)

    video_path = ytdlp.download(url, config.cache_dir())
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
