"""The site must not claim a limitation the code no longer has.

🔴 Why this exists: `site/src/pages/limits.astro` said "Threads 抓不了" for as
long as that was true. It stopped being true the moment the Threads crawler
merged (#153) -- and nothing anywhere would have noticed. The page's own rule
is "只寫實際遇到過的事", which is a rule about what goes *in*; nothing was
watching what should come *out*.

⚠️ This pins the seam between a capability and the sentence that denies it, not
the wording of either. A reworded entry that still says the crawler does not
exist will still fail; a rewritten page that no longer mentions Threads passes,
because then there is no false claim to catch.
"""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIMITS = ROOT / "site" / "src" / "pages" / "limits.astro"
INDEX = ROOT / "site" / "src" / "pages" / "index.astro"


@pytest.mark.skipif(not LIMITS.exists(), reason="site not checked out")
def test_limits_page_does_not_deny_a_crawler_that_exists():
    from reel_scout import crawl

    page = LIMITS.read_text(encoding="utf-8")
    # platform -> phrases that would be false once the platform is crawlable
    denials = {
        "threads": ("Threads 抓不了", "Threads 沒辦法抓", "抓不了 Threads"),
        "youtube": ("YouTube 抓不了",),
        "instagram": ("Instagram 抓不了",),
    }
    for platform, phrases in denials.items():
        if platform not in crawl._CRAWLERS:
            continue
        for phrase in phrases:
            assert phrase not in page, (
                "%s has a registered crawler but the limits page still says "
                "%r" % (platform, phrase))


WORKFLOW = ROOT / ".github" / "workflows" / "site.yml"


@pytest.mark.skipif(not WORKFLOW.exists(), reason="site not checked out")
def test_front_page_platform_gate_lists_every_crawler():
    """The CI gate's platform list must match the crawler registry.

    🔴 Why the check is split in two: whether the front page *names* a platform
    has to be measured on the rendered page, because `index.astro` carries two
    consts (`diffs`, `layers`) that are defined and never mapped -- dead copy
    that a source-level grep happily counts. Measured: the source says "Threads"
    twice, the built page once. So the naming check lives in `site.yml`, which
    runs after `astro build` and greps `dist/`.

    That workflow has no reel-scout installed, so its platform list is written
    out by hand. This test is what stops that list from drifting: add a crawler
    without adding it there and the suite goes red.
    """
    from reel_scout import crawl

    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "for p in "
    line = next(l for l in text.splitlines() if marker in l and "dist/index.html" not in l)
    listed = set(line.split(marker, 1)[1].split(";")[0].split())
    assert listed == set(crawl._CRAWLERS), (
        "site.yml front-page gate lists %s but the registry has %s"
        % (sorted(listed), sorted(crawl._CRAWLERS)))
