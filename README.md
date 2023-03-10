# talk2pdf

## Prerequisites

You will need an OpenAI API key.
1. Create an account
2. Go to [platform.openai.com](https://platform.openai.com)
    1. Click on your account inthe top right
    2. Click View API Keys
    3. Click "Create new secret key"
    4. You will need to provide this API key to talk2pdf (see below)

You will need some software in your path:
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
```
pipenv shell
pip install -r requirements/prod.txt

export OPENAPI_SECRET=sk-...
python talk2pdf/py <youtube-url>
```

Or, with an existing video file
```
pipenv shell
pip install -r requirements/prod.txt

export OPENAPI_SECRET=sk-...
python talk2pdf/py <video-file>
```

## Configuration

`talk2pdf.py` looks in `TALK2PDF_CONFIG_DIR`, then `XDG_CONFIG_HOME/talk2pdf`, and finally `$HOME/.config/talk2pdf` for a `config.json` file.
You can put your OpenAI key in there instead of setting it in the environment

```json
{
  "openapi_secret": "sk-..."
}
```

`talk2pdf.py` uses `TALK2PDF_CACHE_DIR`, or `XDG_CACHE_HOME/talk2pdf`, or finally `$HOME/.cache/talk2pdf` as a cache directory.
This is where intermediate files are stored.


## Roadmap

- [ ] add timestamps to each paragraph