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
