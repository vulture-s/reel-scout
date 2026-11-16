"""Two entries with the same label must not share one bundle directory.

A class form routinely has one student submit two reels under the same name.
Both slugged to the same directory; bundle filenames come from the title, and
Instagram titles are "Video by <handle>", so the second reel's page overwrote
the first and the manifest still listed both as done.
"""
from reel_scout import batch


def test_same_label_entries_get_distinct_bundle_dirs(temp_db, tmp_path, monkeypatch):
    exported = []
    ids = iter(["vid_one", "vid_two"])

    def fake_run(cmd, verbose, timeout=None):
        if "export" in cmd:
            exported.append(cmd[cmd.index("-o") + 1])
        return 0

    monkeypatch.setattr(batch, "_run", fake_run)
    monkeypatch.setattr(batch, "resolve_video_id", lambda conn, before, url: next(ids))
    entries = [("小明", "https://www.instagram.com/reel/AAA111/"),
               ("小明", "https://www.instagram.com/reel/BBB222/")]
    result = batch.run_batch(entries, str(tmp_path / "out"), "agent", score=False)

    dirs = [e["bundle_dir"] for e in result["done"]]
    assert len(dirs) == 2
    assert dirs[0] != dirs[1]
    assert exported[0] != exported[1]
    # The first keeps the plain name, so a batch without duplicates is unchanged.
    assert dirs[0].endswith("小明")


def test_distinct_labels_keep_their_plain_slugs(temp_db, tmp_path, monkeypatch):
    ids = iter(["a", "b"])
    monkeypatch.setattr(batch, "_run", lambda cmd, verbose, timeout=None: 0)
    monkeypatch.setattr(batch, "resolve_video_id", lambda conn, before, url: next(ids))
    entries = [("Amy", "https://www.instagram.com/reel/AAA111/"),
               ("Bob", "https://www.instagram.com/reel/BBB222/")]
    result = batch.run_batch(entries, str(tmp_path / "out"), "agent", score=False)
    assert [e["slug"] for e in result["done"]] == ["Amy", "Bob"]
