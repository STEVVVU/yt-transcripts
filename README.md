# yt-transcripts

A Python CLI that takes YouTube video and/or playlist links and writes one plain-text
transcript file per video.

## Why

It is free and keyless. There is no API key to register, no paid proxy or scraping
service in the loop, and no daily quota to run out of. The tool reads the same public
caption endpoints your browser does through
[`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api), and uses
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp) for playlist enumeration, titles, and as a
subtitle-only fallback. Video and audio are never downloaded.

## Contents

- [Requirements](#requirements)
- [Install](#install)
- [Quick start](#quick-start)
- [Usage](#usage)
- [Flags](#flags)
- [Accepted input forms](#accepted-input-forms)
- [The `v=` + `list=` precedence rule](#the-v--list-precedence-rule)
- [Output format](#output-format)
- [How it works](#how-it-works)
- [Resilience and resuming](#resilience-and-resuming)
- [Exit codes](#exit-codes)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Known limitations](#known-limitations)
- [License](#license)

## Requirements

- Python 3.11 or newer. Developed and tested on 3.11.9.
- Windows, macOS, or Linux. Output filenames are sanitized to be valid on Windows on
  every platform, so transcript directories stay portable.
- Dependencies (installed by `requirements.txt`):
  - `youtube-transcript-api>=1.2.4,<2` — verified against 1.2.4
  - `yt-dlp>=2026.7.4` — verified against 2026.7.4

## Install

```bash
git clone https://github.com/STEVVVU/yt-transcripts.git
cd yt-transcripts
pip install -r requirements.txt
```

A virtual environment is optional but recommended, so the pinned `yt-dlp` version does
not collide with anything else on your system:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

There is no packaging metadata yet, so run the tool as a module from the project
directory: `python -m yt_transcripts`.

## Quick start

Single video:

```bash
python -m yt_transcripts "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

Whole playlist:

```bash
python -m yt_transcripts "https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxx"
```

Several mixed inputs at once, into a custom directory:

```bash
python -m yt_transcripts -o text \
  dQw4w9WgXcQ \
  "https://youtu.be/VIDEO_ID" \
  "https://www.youtube.com/shorts/VIDEO_ID" \
  "https://www.youtube.com/playlist?list=PLxxxxxxxxxxxxxxxx"
```

Progress goes to stderr, one line per video, plus a final summary:

```text
[1/10] OK   0eKVizvYSUQ  (manual, en)
[2/10] SKIP us9tUY_yN7Y  (How-Autocomplete-works-on-Google-Search-us9tUY_yN7Y.txt)
[3/10] OK   dQw4w9WgXcQ  (manual, en)
...
10 videos: 10 ok, 0 skipped, 0 failed
```

Because diagnostics and progress are on stderr, `2>/dev/null` gives you a silent run and
the files still land in the output directory.

## Usage

```text
usage: yt-transcripts [-h] [-o DIR] [--langs LANGS] [--playlist] [--overwrite]
                      [--keep-markers] [--no-fallback] [-q | -v]
                      URL_OR_ID [URL_OR_ID ...]

Write plain-text transcripts for YouTube videos and playlists.

positional arguments:
  URL_OR_ID

options:
  -h, --help            show this help message and exit
  -o DIR, --output DIR  output directory (default: ./transcripts)
  --langs LANGS         comma-separated language preferences
  --playlist            prefer list= when a URL also identifies a single video
  --overwrite           replace existing non-empty transcript files
  --keep-markers        keep bracketed markers such as [Music]
  --no-fallback         disable the yt-dlp subtitle fallback
  -q, --quiet           suppress diagnostics
  -v, --verbose         enable debug diagnostics
```

## Flags

| Flag | Default | Description |
| --- | --- | --- |
| `URL_OR_ID ...` | required | One or more video URLs, video IDs, playlist URLs, or playlist IDs, in any mixture. |
| `-o DIR`, `--output DIR` | `./transcripts` | Output directory. Created if missing, including parent directories. |
| `--langs CODES` | `en,en-US,en-GB` | Comma-separated original-language preferences, best first. Only original caption tracks are considered; machine translations are never requested. |
| `--playlist` | off | For a URL that names both a video and a playlist, use the playlist. See [the precedence rule](#the-v--list-precedence-rule). |
| `--overwrite` | off | Refetch and replace existing non-empty transcript files instead of skipping them. |
| `--keep-markers` | off | Keep bracketed non-speech markers such as `[Music]` and `[Applause]` in the body text. |
| `--no-fallback` | off | Disable the yt-dlp subtitle fallback; a primary failure becomes an immediate per-video failure. |
| `-q`, `--quiet` | off | Suppress diagnostic logging. Per-video progress lines and the summary are still printed. Mutually exclusive with `-v`. |
| `-v`, `--verbose` | off | Enable debug-level logging. See [Known limitations](#known-limitations) — this currently changes nothing visible. |
| `-h`, `--help` | — | Print usage and exit. |

## Accepted input forms

| Input | Resolves to | Notes |
| --- | --- | --- |
| `https://www.youtube.com/watch?v=VIDEO_ID` | video | The standard watch URL. |
| `https://youtu.be/VIDEO_ID` | video | Share-link short form; the ID is in the path. |
| `https://www.youtube.com/shorts/VIDEO_ID` | video | ID in the path. |
| `https://www.youtube.com/embed/VIDEO_ID` | video | ID in the path. |
| `https://m.youtube.com/watch?v=VIDEO_ID` | video | `youtube.com`, `www.youtube.com`, and `m.youtube.com` are all recognized. |
| `VIDEO_ID` | video | A bare ID: exactly 11 characters from `A-Z a-z 0-9 _ -`. |
| `https://www.youtube.com/playlist?list=PLAYLIST_ID` | playlist | The standard playlist URL. |
| `PLAYLIST_ID` | playlist | A bare ID starting with `PL`, `UU`, `OL`, `LL`, or `FL`. |
| `https://youtu.be/videoseries?list=PLAYLIST_ID` | playlist | `videoseries` is a playlist placeholder path, not a video ID, and is treated as such. |
| any `http(s)` URL carrying `?list=PLAYLIST_ID` and no video | playlist | The `list=` query is honored on any host, because YouTube emits playlist links through several hostnames and redirect surfaces. |
| any `http(s)` URL carrying `?v=VIDEO_ID` | video | The `v=` query is honored on any host, for the same reason. |

Notes on ambiguity:

- A bare string of exactly 11 valid characters is always read as a **video ID**, even if
  it starts with `PL` or `UU`. Real playlist IDs are never exactly 11 characters
  (`PL` + 16 or 32, `UU` + 22), so an 11-character match is unambiguous.
- Anything else — a non-YouTube URL, a bare string that is neither shape, an empty
  argument — is a usage error and exits `2` with the message
  `Unrecognized YouTube input: '...'`.

## The `v=` + `list=` precedence rule

**Any URL that names a specific video is treated as a single video by default, even when
it also carries `list=`.** Pass `--playlist` to fetch the whole playlist instead.

This applies whether the video is named by the `v=` query or by the URL path:

```text
https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST_ID   -> 1 video
https://youtu.be/VIDEO_ID?list=PLAYLIST_ID                  -> 1 video
https://www.youtube.com/shorts/VIDEO_ID?list=PLAYLIST_ID    -> 1 video
https://www.youtube.com/embed/VIDEO_ID?list=PLAYLIST_ID     -> 1 video

# same links, with --playlist
python -m yt_transcripts --playlist "https://youtu.be/VIDEO_ID?list=PLAYLIST_ID"
                                                            -> the entire playlist
```

Why this default matters: when you are watching a video from inside a playlist and hit
YouTube's **Share** button, YouTube appends `?list=...` to the link it gives you. That
link looks like a single-video link and is almost always meant as one — but a naive
parser sees `list=` and expands it. The default here protects you from pasting one
apparently ordinary link and accidentally pulling hundreds of transcripts.

A URL with `list=` and **no** video (`/playlist?list=...`, `youtu.be/videoseries?list=...`)
is a playlist with or without `--playlist`.

## Output format

One UTF-8 `.txt` file per video, named:

```text
<Sanitized-Title>-<videoId>.txt
```

Sanitizing removes characters illegal in Windows filenames (`< > : " / \ | ? *`) and
control characters, collapses whitespace runs into single hyphens, and truncates to 80
characters. The **video ID is always appended** so that two videos with the same title —
common with lecture series, `Part 1`-style naming, and re-uploads — cannot overwrite each
other. If no title can be obtained at all, the file is just `<videoId>.txt`.

Each file opens with a four-line header, a blank line, a `---` rule, another blank line,
and then the transcript prose:

```text
Title: How ads appear in Google Search
URL: https://www.youtube.com/watch?v=j0q_7SRcLWY
Language: en
Captions: manual

---

NARRATOR: When you're on the hunt for something-- say, the perfect camping chair-- you
might come to Google for help. And when you do, we'll end up showing you a lot of
information about camping chairs. A page like this actually displays two types of
information related to your search-- search results and ads.
```

- `Language` is the caption track's language code, e.g. `en`, `en-GB`.
- `Captions` is `manual` or `auto-generated`.
- Body text is rewrapped at 100 characters, without breaking long words or hyphenated
  words. Blank-line-separated paragraphs are preserved.
- Bracketed non-speech markers are stripped unless `--keep-markers` is passed. The
  stripped set is a fixed list of single-word markers, case-insensitive: `[Music]`,
  `[Applause]`, `[Laughter]`, `[Laughs]`, `[Cheering]`, `[Noise]`, `[Silence]`,
  `[Inaudible]`, `[Foreign]`, `[Sigh]`/`[Sighs]`, `[Gasp]`/`[Gasps]`, `[Clapping]`.
  Multi-word variants that some caption authors use, such as `[MUSIC PLAYING]`, are not
  in that list and survive.

## How it works

- `yt-dlp` enumerates playlists with flat extraction, yielding a `(video_id, title)`
  pair per entry. Unavailable, malformed, or ID-less entries are logged and skipped
  rather than aborting the playlist.
- `youtube-transcript-api` fetches the caption text for each video ID. This is the
  primary path and requires no key.
- Manually created captions are preferred over auto-generated ones, since human-authored
  tracks are punctuated and generally cleaner.
- Machine-translated caption tracks are deliberately never requested. `translate()` is
  never called, and the yt-dlp fallback resolves exact original-track keys instead of
  wildcard language patterns. Translated tracks are the ones YouTube answers with HTTP
  429 ([yt-dlp #13831](https://github.com/yt-dlp/yt-dlp/issues/13831)), so a video whose
  only match is a translation is reported as having no transcript.
- A subtitle-only `yt-dlp` download is the per-video fallback when the primary path
  fails in a way the alternate extractor can plausibly fix — no track found, captions
  reported disabled, a PO-token requirement, unparsable response data, or a nominally
  successful but empty response
  ([youtube-transcript-api #592](https://github.com/jdepoix/youtube-transcript-api/issues/592)).
  The fallback prefers JSON3 subtitles over VTT and collapses YouTube's repeated rolling
  auto-caption cues. Disable it with `--no-fallback`.
- Blocked requests are not sent down the fallback path; they are retried with backoff
  instead. See below.

## Resilience and resuming

- **Skip-if-exists.** Before fetching, the tool looks for a non-empty `*-<videoId>.txt`
  in the output directory. If one exists, the video is skipped and counted as `skipped`.
  Re-running a playlist that was interrupted therefore only fetches what is missing.
  Pass `--overwrite` to force a refetch of everything.
- **Jittered pacing.** A random 1.5–3.0 second delay is inserted between videos, but
  only after a video that actually hit the network — resuming a mostly complete playlist
  does not sleep between skips.
- **Block backoff.** An `IpBlocked` or `RequestBlocked` response is retried after 60
  seconds, then after 120 seconds, for a maximum of 2 retries per video. If it is still
  blocked, that video is recorded as failed and the run continues.
- **No aborts.** A single failing video never ends the run. Failures are logged, counted,
  and reflected in the exit code. A nonexistent video ID passed alongside a good one
  yields `2 videos: 1 ok, 0 skipped, 1 failed` and exit `1`, with no traceback.
- **Titles degrade gracefully.** If metadata for a single video cannot be retrieved, the
  video ID is used as the title and the transcript is still fetched.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | At least one transcript was written or skipped as already present, and nothing failed. |
| `1` | Nothing was produced at all (empty playlist, all videos unavailable), or the run mixed successes and failures. |
| `2` | Usage error — an unrecognized input, a `--langs` value with no language codes, or bad arguments. |

Note that "produced nothing" is a failure even when no individual video raised: an empty
playlist exits `1` rather than `0`.

## Troubleshooting

### `IpBlocked` / `RequestBlocked`

YouTube is throttling your address. The tool already retries at 60s and 120s; if a video
still fails, wait and re-run the same command later. Skip-if-exists makes resuming cheap,
so a second run only fetches what the first one missed.

Cloud and datacenter IP ranges are blocked far more aggressively than residential ones.
If you are running this on an EC2 instance, a VPS, or a CI runner, expect frequent blocks
— free, proxy-less operation cannot guarantee access from those addresses. Running from a
home connection is dramatically more reliable.

### Age-restricted videos fail

Cookie authentication is currently non-functional upstream in
`youtube-transcript-api`, so there is no working way to authenticate an age-restricted
request. These videos are recorded as failed and the run continues with the rest.

### "Captions disabled" videos

If the uploader genuinely disabled captions and YouTube generated none, there is no
transcript to retrieve. The yt-dlp fallback is attempted, but it cannot create captions
that do not exist.

### Extraction suddenly breaks across the board

If playlist enumeration or the fallback stops working for everything at once, YouTube
almost certainly changed something. `yt-dlp` is the component that rots fastest against
those changes:

```bash
pip install -U yt-dlp
```

If that fixes it, also consider updating the other dependency:

```bash
pip install -U youtube-transcript-api
```

### A specific video returns an empty transcript

This is [youtube-transcript-api #592](https://github.com/jdepoix/youtube-transcript-api/issues/592):
some videos return a nominally successful but empty caption response. It is exactly why
the yt-dlp fallback exists, so do not pass `--no-fallback` if you are hitting this.

## Development

Run the test suite:

```bash
python -m pytest tests/ -q
```

```text
52 passed
```

The suite is fully offline — all network interaction is stubbed, so no YouTube requests
are made and no credentials or connectivity are required.

Layout:

```text
yt_transcripts/
  __init__.py
  __main__.py      # module entry point
  cli.py           # argument parsing, job loop, backoff, exit codes
  urls.py          # input parsing and the v=/list= precedence rule
  playlist.py      # yt-dlp playlist enumeration and title lookup
  transcript.py    # youtube-transcript-api primary path + yt-dlp fallback
  textout.py       # text cleanup, wrapping, filenames, file writing
tests/
  test_cli.py
  test_textout.py
  test_transcript.py
  test_urls.py
```

## Known limitations

Stated plainly rather than glossed over:

- **`-v` / `--verbose` currently produces no extra output.** Logging is configured at
  `DEBUG` level when the flag is passed, but no debug-level statements exist in the code
  yet, so the flag is accepted and has no visible effect.
- **The yt-dlp fallback path has not been exercised against a live video that needs it.**
  It is covered by unit tests with stubbed extraction, but no real-world video that
  triggers it has been confirmed end to end.
- **No packaging metadata.** There is no `pyproject.toml`, so there is no
  `pip install .` and no `yt-transcripts` console script. Run it as
  `python -m yt_transcripts` from the project directory.
- **No proxy or cookie support.** By design — the goal is keyless, cost-free operation —
  but it means a hard IP block has no workaround other than waiting or changing network.
- **Timestamps are not preserved.** Output is continuous prose. There is no SRT/VTT
  passthrough and no per-cue timing in the written files.

## License

MIT. Use it, fork it, ship it; no warranty.
