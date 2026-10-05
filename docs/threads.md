# Threads

How reel-scout handles a Threads post: what it fetches, what it analyzes, what
it only stores, and the one assumption all of it rests on.

## The rule

| In the post | What happens | Where it lands |
|---|---|---|
| **First video** | Downloaded and **analyzed** (transcript, keyframes, VLM, score) | its own `videos` row, `platform_id = <code>` |
| **Photos** | Downloaded and **stored**, not analyzed | `post_media` (`kind = image`, `file_path`) |
| **Other videos** | **Listed**, not downloaded | `post_media` (`kind = video`, no file) |
| **Caption, follow-ups, counts** | Stored | `post_meta` |
| Another video, on request | Analyzed as its own clip | new `videos` row, URL `<post url>?media=N`, `platform_id = <code>#N` |

"First" means first in display order — the order a person sees when swiping.
Items are numbered from 1 in that order, and `?media=N` refers to that number.

### Why the first video and not all of them

One post, one score. A carousel of three 7-second clips is usually one idea cut
into pieces, and scoring each piece separately says nothing about the post.
Joining them into one file is worse: every join counts as a cut and distorts
the pacing score. So the post gets one analysis by default, and any other video
is one click away (below).

### Why photos are downloaded but other videos are not

Every media URL Threads hands out is **signed and expires**. A photo is small,
so it is saved on the spot or it is gone. A video that nobody has asked about is
not worth the download; and when someone does ask, the stored URL may already
be dead — so the on-demand analysis fetches the post page again for a fresh
URL instead of trusting `post_media.source_url`.

### Counts are a snapshot

`like_count`, `reply_count`, `repost_count`, `quote_count` are what the page
said at `fetched_at`. A later re-crawl overwrites them (and refreshes the
caption), but never forgets which items already have an analysis of their own.

## Analyzing another video in the post

1. In `reel-scout view`, open the clip. The **Post** section lists every item;
   a video without its own analysis has a **queue analysis** button.
2. The button writes one row to `analysis_requests`. **The viewer never runs
   the pipeline** — it is the same narrow write exception annotations already
   have, and for the same reason: the viewer has no account layer, so anything
   it exposes is exposed to everyone who can reach it.
3. On the machine with the pipeline:

   ```
   reel-scout pending          # what is queued
   reel-scout pending --run    # analyze each one (scored; --no-score to skip)
   ```

   A request is marked `done` only if the DB shows its row `analyzed`; anything
   else is `failed` with the reason, and pressing the button again re-queues it.

The same thing without the viewer: `reel-scout analyze "<post url>?media=N" --score`.

## How it fetches, and why it is fragile

yt-dlp has no Threads extractor, and the post code is not an Instagram shortcode
in disguise (the same ID on `instagram.com/p/` is refused even with valid
cookies). What works is the post page itself: Threads serves browsers a login
wall, but serves **search crawlers** a server-rendered page whose embedded JSON
carries the whole post.

That makes **the User-Agent the single assumption** everything rests on. It
lives in `THREADS_USER_AGENT` (default: Googlebot), not in the crawler, so it
can be changed without a release. There is no official guarantee behind it;
Meta can close it any day — for instance by verifying that a "Googlebot"
request really comes from Google.

What is guaranteed is that it fails **loud**: a page with no post in it raises
an error naming the User-Agent, instead of producing an empty row that looks
like a successful crawl.

Two shapes in the page that were learned by running it live, not by reading it:

- **A post arrives in fragments.** Several `result.data.media` objects share
  the post's `id`; the follow-up posts sit in a different fragment from the
  caption. Reading only the fragment that has the post code returned zero
  follow-ups for a post that had one, with nothing failing. They are merged.
- **Replies look like posts.** They carry `code`, `caption` and their own
  `video_versions`, but are nested inside the root post — never at
  `result.data.media` — so the root is never mistaken for a reply.

## Not covered

- Photo-only posts: there is no video to analyze, so they are refused.
- Instagram does not fill `post_meta` / `post_media` yet; the tables are not
  Threads-specific, only the crawler that fills them is.
