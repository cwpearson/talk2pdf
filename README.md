# talk2pdf

talk2pdf converts videos of talks into a PDF with the transcript and associated screenshots.

## Prerequisites

talk2pdf uses OpenAI's APIs -- you will need an OpenAI API key.

> **Note**
> talk2pdf ONLY uses your API key to make OpenAPI calls. It is not otherwise used, stored, or transmitted.

1. Create an OpenAI account
2. Go to [platform.openai.com](https://platform.openai.com)
    1. Click on your account in the top right
    2. Click View API Keys
    3. Click "Create new secret key"
    4. You will need to provide this API key to talk2pdf (see below)

`talk2pdf` uses FFmpeg for video/audio operations and yt-dlp to download video from online streaming services.

```
brew install ffmpeg yt-dlp
```

```
apt-get install ffmpeg yt-dlp
```

## Running

> **Warning**
> This will cost ~$0.50 / hr of video

This will generate a PDF in the current directory:

With a youtube video
```bash
pipenv shell
pip install talk2pdf

export OPENAPI_SECRET=sk-...
python -m talk2pdf <youtube-url>
```

Or, with an existing video file
```bash
pipenv shell
pip install talk2pdf

export OPENAPI_SECRET=sk-...
python -m talk2pdf <video-file>
```

## Configuration

`talk2pdf` looks in `TALK2PDF_CONFIG_DIR`, then `XDG_CONFIG_HOME/talk2pdf`, and finally `$HOME/.config/talk2pdf` for a `config.json` file.
You can put your OpenAI key in there instead of setting it in the environment

```json
{
  "openapi_secret": "sk-..."
}
```

`talk2pdf` uses `TALK2PDF_CACHE_DIR`, or `XDG_CACHE_HOME/talk2pdf`, or finally `$HOME/.cache/talk2pdf` as a cache directory.
This is where intermediate files are stored.

## Contributing

```bash
pipenv shell
pip install --editable .
python -m talk2pdf ...
```

```
pip install --upgrade build twine
python -m build
python3 -m twine upload dist/*
```

## Roadmap

- [ ] add timestamps to each paragraph