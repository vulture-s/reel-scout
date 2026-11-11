"""CLAP sound search: front end, tokenizer trap, schema, backfill, ranking, CJK.

Nothing here needs the 780 MB model except the last test, which skips itself
when the model directory is absent. The ONNX sessions are scripted fakes; the
numbers that matter (front-end shape and padding, tokenizer mask, window
geometry, ranking) are tested on the real code paths.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest

np = pytest.importorskip("numpy")

from reel_scout import config, db  # noqa: E402
from reel_scout.audio import clap, clap_search  # noqa: E402

SR = clap.SR


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db.init_db(conn)
    return conn


def _video(conn, vid, file_path=None, status="analyzed", title=None):
    conn.execute("INSERT INTO videos (id, platform, platform_id, url, file_path, status, title) "
                 "VALUES (?,?,?,?,?,?,?)",
                 (vid, "local", vid, "u:" + vid, file_path, status, title or vid))
    conn.commit()


def _unit(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


# --- front end -----------------------------------------------------------------

def test_repeatpad_tiles_then_zero_pads_to_ten_seconds():
    x = np.arange(1, 100001, dtype=np.float32)          # 100000 samples, 2.08 s
    y = clap.pad_repeat(x)
    assert y.shape == (clap.N,)
    reps = int(clap.N / len(x))                          # 4, as np.tile(x, int(N/len))
    assert np.array_equal(y[:reps * len(x)], np.tile(x, reps))
    assert not y[reps * len(x):].any()                   # the remainder is zeros, not a 5th partial copy
    full = np.ones(clap.N, np.float32)
    assert np.array_equal(clap.pad_repeat(full), full)
    with pytest.raises(ValueError):
        clap.pad_repeat(np.ones(clap.N + 1, np.float32))


def test_log_mel_shape_and_floor():
    mel = np.abs(np.random.default_rng(0).standard_normal((513, 64)))
    out = clap.log_mel(np.zeros(clap.N, np.float32), mel)
    assert out.shape == (1001, 64) and out.dtype == np.float32
    assert np.allclose(out, -100.0)                      # 10*log10(1e-10): the max(1e-10, .) floor
    f = clap.features([np.zeros(1000, np.float32), np.zeros(clap.N, np.float32)], mel)
    assert f.shape == (2, 1, 1001, 64)


def test_log_mel_puts_a_tone_in_its_bin():
    # identity-like "mel": one band per FFT bin for the first 64 bins
    mel = np.zeros((513, 64))
    mel[np.arange(64), np.arange(64)] = 1.0
    k = 20                                                # bin 20 = 20 * 48000 / 1024 Hz
    t = np.arange(clap.N) / float(SR)
    x = np.sin(2 * np.pi * (k * SR / 1024.0) * t).astype(np.float32)
    out = clap.log_mel(x, mel)
    assert int(np.argmax(out[500])) == k


def test_hann_is_periodic():
    w = clap.hann_periodic(1024)
    assert w[0] == 0.0
    assert np.allclose(w[1:], w[1:][::-1])               # periodic: w[k] == w[n-k]
    assert w[512] == pytest.approx(1.0)


@pytest.mark.parametrize("secs,starts", [
    (0, []), (3, [0]), (10, [0]), (12, [0, 5]), (14, [0, 5]), (20, [0, 5, 10]), (21, [0, 5, 10, 15]),
])
def test_window_starts(secs, starts):
    assert clap.window_starts(int(secs * SR)) == [s * SR for s in starts]


needs_ffmpeg = pytest.mark.skipif(shutil.which(config.FFMPEG_BIN) is None and shutil.which("ffmpeg") is None,
                                  reason="ffmpeg not installed")


@needs_ffmpeg
@pytest.mark.parametrize("secs", [3, 10, 23])
def test_stream_windows_matches_in_memory_windowing(tmp_path, secs):
    p = str(tmp_path / "tone.wav")
    subprocess.run([config.FFMPEG_BIN, "-v", "error", "-f", "lavfi", "-i",
                    "aevalsrc=0.1*sin(2*PI*440*t):s=48000:d=%d" % secs,
                    "-ac", "1", "-c:a", "pcm_f32le", p], check=True)
    got = list(clap.stream_windows(p))
    assert [(i, s) for i, s, _, _ in got] == [
        (i, st / float(SR)) for i, st in enumerate(clap.window_starts(secs * SR))]
    assert got[-1][2] == pytest.approx(secs, abs=0.01)   # the last window reaches the end
    assert all(len(w) == round((e - s) * SR) <= clap.N for _, s, e, w in got)
    # the streamed samples are the decoded samples, not a re-chunked approximation
    if len(got) > 1:
        assert np.array_equal(got[0][3][clap.HOP_N:], got[1][3][:clap.N - clap.HOP_N])


@needs_ffmpeg
def test_stream_windows_no_audio_stream(tmp_path):
    p = str(tmp_path / "video_only.mp4")
    subprocess.run([config.FFMPEG_BIN, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
                    "-pix_fmt", "yuv420p", p], check=True)
    with pytest.raises(clap.NoAudio):
        list(clap.stream_windows(p))


# --- the tokenizer trap -----------------------------------------------------------

def _tiny_tokenizer():
    tokenizers = pytest.importorskip("tokenizers")
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace

    vocab = {"<pad>": 1, "<unk>": 3}
    for i, w in enumerate("a dog barking long sentence about crowded restaurant at night".split()):
        vocab[w] = 10 + i
    tok = tokenizers.Tokenizer(WordLevel(vocab, unk_token="<unk>"))
    tok.pre_tokenizer = Whitespace()
    # The trap: the model's tokenizer.json ships with padding switched on.
    tok.enable_padding(pad_id=1, pad_token="<pad>")
    return tok


def test_tokenizer_mask_counts_real_tokens_not_padded_length():
    tok = _tiny_tokenizer()
    texts = ["a dog barking", "long sentence about crowded restaurant at night a dog"]
    # what goes wrong without no_padding(): every row reports the padded length
    bad = tok.encode_batch(texts)
    assert len(bad[0].ids) == len(bad[1].ids) == 9
    ids, mask = clap.tokenize(tok, texts)
    assert mask.sum(axis=1).tolist() == [3, 9]
    assert ids[0, 3:].tolist() == [1] * 6                # right-padded with <pad>


class _MeanPoolText:
    """Fake text graph: masked mean of a fixed per-id vector, like a real pooler would be."""

    def __init__(self):
        self.table = np.random.default_rng(1).standard_normal((64, clap.DIM)).astype(np.float32)

    def run(self, _outs, feeds):
        ids, mask = feeds["input_ids"], feeds["attention_mask"].astype(np.float32)
        v = self.table[ids] * mask[..., None]
        return [v.sum(1) / mask.sum(1, keepdims=True)]


def test_text_embedding_is_the_same_alone_and_in_a_batch():
    m = clap.ClapOnnx(None, _MeanPoolText(), _tiny_tokenizer(), None)
    alone = m.embed_text(["a dog barking"])[0]
    batched = m.embed_text(["a dog barking",
                            "long sentence about crowded restaurant at night a dog"])[0]
    assert float(alone @ batched) == pytest.approx(1.0, abs=1e-6)


# --- dependencies and model files ----------------------------------------------------

def test_missing_extra_names_the_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "tokenizers", None)
    with pytest.raises(clap.ClapUnavailable) as e:
        clap.require_deps()
    assert "tokenizers" in str(e.value) and "reel-scout[clap]" in str(e.value)
    assert clap.availability() is not None


def test_missing_model_files_say_where_to_get_them(tmp_path):
    with pytest.raises(clap.ClapUnavailable) as e:
        clap.check_model_dir(str(tmp_path), "fp32")
    msg = str(e.value)
    assert "clap_audio.onnx" in msg and "REEL_SCOUT_CLAP_DIR" in msg
    assert "scripts/export_clap_onnx.py" in msg and clap.MODEL_REVISION in msg


def test_wrong_file_is_refused_by_hash(tmp_path):
    for f in (clap.AUDIO_FILES["fp32"], clap.TEXT_FILE, clap.MEL_FILE, clap.TOKENIZER_FILE):
        (tmp_path / f).write_bytes(b"not the model")
    assert clap.check_model_dir(str(tmp_path), "fp32", verify_hash=False)["audio"].endswith("clap_audio.onnx")
    with pytest.raises(clap.ClapUnavailable) as e:
        clap.check_model_dir(str(tmp_path), "fp32")
    assert "sha256" in str(e.value)


def test_variant_is_validated(monkeypatch):
    monkeypatch.setattr(config, "CLAP_AUDIO_VARIANT", "fp16")
    with pytest.raises(clap.ClapUnavailable):
        clap.audio_variant()


def test_default_model_dir_is_under_the_data_dir(monkeypatch):
    monkeypatch.setattr(config, "CLAP_MODEL_DIR", "")
    monkeypatch.setattr(config, "DATA_DIR", "/x/data")
    assert clap.model_dir() == os.path.join("/x/data", "models", "clap", "larger_clap_general@16c8cc3")


# --- schema ---------------------------------------------------------------------

def test_fresh_install_has_the_clap_tables_and_roundtrips():
    conn = _conn()
    _video(conn, "v1")
    e = _unit(np.arange(clap.DIM))
    db.save_audio_clap(conn, "v1", windows=[(0, 0.0, 10.0, e.tobytes()), (1, 5.0, 12.0, e.tobytes())],
                       mean_emb=e.tobytes(), model=clap.MODEL_ID, revision=clap.MODEL_REVISION,
                       variant="fp32", dim=clap.DIM, window_s=10.0, hop_s=5.0, duration_s=12.0)
    row = db.get_audio_clap(conn, "v1")
    assert row["n_windows"] == 2 and row["variant"] == "fp32"
    assert np.array_equal(clap.blob_to_emb(row["mean_emb"]), e)
    # replace, not append
    db.save_audio_clap(conn, "v1", windows=[(0, 0.0, 3.0, e.tobytes())], mean_emb=e.tobytes(),
                       model=clap.MODEL_ID, revision=clap.MODEL_REVISION, variant="int8",
                       dim=clap.DIM, window_s=10.0, hop_s=5.0, duration_s=3.0)
    assert conn.execute("SELECT COUNT(*) FROM audio_clap_windows").fetchone()[0] == 1
    assert db.db_stats(conn)["audio_clap"] == 1


def test_migration_from_v23_adds_the_tables():
    conn = _conn()
    conn.execute("DROP TABLE audio_clap")
    conn.execute("DROP TABLE audio_clap_windows")
    conn.execute("UPDATE schema_version SET version = 23")
    conn.commit()
    db.init_db(conn)
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION == 24
    conn.execute("SELECT video_id, idx, start_s, end_s, emb FROM audio_clap_windows")
    conn.execute("SELECT revision, variant, mean_emb FROM audio_clap")


# --- ranking ----------------------------------------------------------------------

def _meta_mat():
    q = _unit([1.0] + [0.0] * (clap.DIM - 1))
    other = _unit([0.0, 1.0] + [0.0] * (clap.DIM - 2))

    def at(c):
        return _unit(c * q + np.sqrt(max(0.0, 1 - c * c)) * other)

    meta = [("A", 0, 0.0, 10.0), ("A", 1, 5.0, 15.0), ("A", 2, 10.0, 20.0), ("A", 3, 15.0, 22.0),
            ("B", 0, 0.0, 10.0), ("B", 1, 5.0, 12.0)]
    scores = [0.10, 0.80, 0.79, 0.20, 0.70, 0.30]
    return meta, np.stack([at(s) for s in scores]), q


def test_rank_orders_windows_by_cosine():
    meta, mat, q = _meta_mat()
    hits = clap_search.rank(meta, mat, q, top=3)
    assert [(h["video_id"], h["window"]) for h in hits] == [("A", 1), ("A", 2), ("B", 0)]
    assert hits[0]["score"] == pytest.approx(0.80, abs=1e-3)
    assert hits[0]["start_s"] == 5.0 and hits[0]["end_s"] == 15.0


def test_rank_per_video_merges_adjacent_near_equal_windows():
    meta, mat, q = _meta_mat()
    hits = clap_search.rank(meta, mat, q, top=5, per_video=True)
    assert [h["video_id"] for h in hits] == ["A", "B"]
    a = hits[0]
    assert (a["start_s"], a["end_s"], a["windows_merged"]) == (5.0, 20.0, 2)   # windows 1+2, not 3 (0.20)
    assert hits[1]["windows_merged"] == 1


class _FakeModel:
    variant = "fp32"

    def __init__(self, vec):
        self.vec = vec
        self.seen = []

    def embed_text(self, texts):
        self.seen.extend(texts)
        return np.stack([self.vec for _ in texts])


def _indexed_conn():
    conn = _conn()
    meta, mat, q = _meta_mat()
    for vid in ("A", "B"):
        _video(conn, vid, title="clip " + vid)
        rows = [(m[1], m[2], m[3], mat[j].tobytes()) for j, m in enumerate(meta) if m[0] == vid]
        db.save_audio_clap(conn, vid, windows=rows, mean_emb=None, model=clap.MODEL_ID,
                           revision=clap.MODEL_REVISION, variant="fp32", dim=clap.DIM,
                           window_s=10.0, hop_s=5.0, duration_s=rows[-1][2])
    # a clip indexed by another revision lives in another space: never searched
    _video(conn, "C")
    db.save_audio_clap(conn, "C", windows=[(0, 0.0, 10.0, q.tobytes())], mean_emb=None,
                       model=clap.MODEL_ID, revision="0" * 40, variant="fp32", dim=clap.DIM,
                       window_s=10.0, hop_s=5.0)
    return conn, q


def test_search_end_to_end_with_a_fake_model():
    conn, q = _indexed_conn()
    m = _FakeModel(q)
    r = clap_search.search(conn, "door slam", top=2, model=m)
    assert r["translated"] is False and r["query_en"] == "door slam"
    assert m.seen == ["door slam"]
    assert r["indexed_videos"] == 2 and r["indexed_windows"] == 6
    assert [h["video_id"] for h in r["results"]] == ["A", "A"]
    assert r["results"][0]["title"] == "clip A"


def test_search_with_nothing_indexed_does_not_load_the_model():
    conn = _conn()

    class Boom:
        def embed_text(self, texts):
            raise AssertionError("model used with an empty index")

    r = clap_search.search(conn, "door slam", model=Boom())
    assert r["results"] == [] and r["indexed_windows"] == 0


# --- CJK queries --------------------------------------------------------------------

def test_cjk_query_is_translated_and_the_english_is_what_gets_searched():
    conn, q = _indexed_conn()
    m = _FakeModel(q)
    r = clap_search.search(conn, "打字聲", model=m, translator=lambda s: "keyboard typing")
    assert r["translated"] is True and r["query"] == "打字聲" and r["query_en"] == "keyboard typing"
    assert m.seen == ["keyboard typing"]


class _LLM:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.prompts = reply, exc, []

    def complete(self, prompt, max_tokens=800, temperature=0.1):
        self.prompts.append(prompt)
        if self.exc:
            raise self.exc
        return self.reply


def test_translate_query_cleans_the_reply():
    llm = _LLM('"Keyboard typing."\n(note: literal)')
    assert clap_search.translate_query("打字聲", llm=llm) == "Keyboard typing"
    assert "打字聲" in llm.prompts[0]


@pytest.mark.parametrize("llm", [_LLM(exc=OSError("connection refused")), _LLM("打字的聲音"), _LLM("")])
def test_failed_translation_never_searches_the_original(llm):
    conn, q = _indexed_conn()
    m = _FakeModel(q)
    with pytest.raises(clap_search.TranslationFailed) as e:
        clap_search.search(conn, "打字聲", model=m, llm=llm)
    assert "打字聲" in str(e.value)
    assert m.seen == []


def test_no_llm_backend_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "nonexistent")
    with pytest.raises(clap_search.TranslationFailed) as e:
        clap_search.translate_query("關門聲")
    assert "LLM_BACKEND=nonexistent" in str(e.value)


def test_has_cjk():
    assert clap_search.has_cjk("打字聲") and clap_search.has_cjk("door 關門")
    assert clap_search.has_cjk("ドア") and not clap_search.has_cjk("door slam — loud!")


# --- backfill + index_video ------------------------------------------------------------

class _FakeFileModel:
    variant = "int8"

    def embed_file(self, path):
        e = _unit(np.ones(clap.DIM))
        return [(0, 0.0, 10.0, e), (1, 5.0, 13.5, e)]


def test_backfill_dry_run_counts_and_writes_nothing(tmp_path, monkeypatch):
    conn = _conn()
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    _video(conn, "have", file_path=str(media))
    _video(conn, "gone", file_path=str(tmp_path / "missing.mp4"))
    _video(conn, "pending", file_path=str(media), status="pending")
    from reel_scout import backfill_clap

    monkeypatch.setattr(clap, "load", lambda *a, **k: pytest.fail("dry run loaded the model"))
    r = backfill_clap.backfill(conn, dry_run=True)
    assert (r["candidates"], r["filled"], r["skipped_no_media"]) == (2, 1, 1)
    assert conn.execute("SELECT COUNT(*) FROM audio_clap").fetchone()[0] == 0


def test_backfill_indexes_with_the_given_model(tmp_path):
    conn = _conn()
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    _video(conn, "have", file_path=str(media))
    from reel_scout import backfill_clap

    r = backfill_clap.backfill(conn, model=_FakeFileModel())
    assert (r["filled"], r["windows"]) == (1, 2)
    row = db.get_audio_clap(conn, "have")
    assert row["variant"] == "int8" and row["duration_s"] == 13.5 and row["n_windows"] == 2
    assert backfill_clap.candidates(conn) == []          # second pass has nothing to do


def test_backfill_without_the_extra_fails_before_touching_anything(tmp_path, monkeypatch):
    conn = _conn()
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    _video(conn, "have", file_path=str(media))
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    from reel_scout import backfill_clap

    with pytest.raises(clap.ClapUnavailable):
        backfill_clap.backfill(conn)


# --- CLI / MCP surfaces ---------------------------------------------------------------

def test_cli_search_sound_on_an_empty_index(temp_db, capsys):
    from reel_scout import cli

    cli.main(["search-sound", "door slam"])
    out = capsys.readouterr().out
    assert "no clips are indexed yet" in out and "backfill-clap" in out


def test_cli_search_sound_untranslatable_query_exits_2(temp_db, capsys, monkeypatch):
    from reel_scout import cli

    monkeypatch.setattr(config, "LLM_BACKEND", "nonexistent")
    with pytest.raises(SystemExit) as e:
        cli.main(["search-sound", "打字聲"])
    assert e.value.code == 2
    assert "CLAP only reads English" in capsys.readouterr().err


def test_mcp_search_sound(temp_db):
    from reel_scout.mcp import tools

    r = tools.call_tool("search_sound", {"query": "door slam"})
    payload = json.loads(r["content"][0]["text"])
    assert payload["results"] == [] and payload["query_en"] == "door slam"
    assert tools.call_tool("search_sound", {"query": " "}).get("isError")


# --- the real model, when this machine has it --------------------------------------------

def _real_model_or_skip():
    why = clap.availability()
    if why:
        pytest.skip("CLAP model not available here: %s" % why)
    return clap.load()


def test_real_model_top1_on_synthetic_sounds():
    """A 1 kHz tone reads as a beep, white noise as rain -- measured 2026-11-12 on the
    pinned export (tone: beep 0.213 vs next 0.110; noise: rain 0.163 vs next -0.011)."""
    m = _real_model_or_skip()
    texts = ["a high pitched beep tone", "a dog barking", "people applauding",
             "rain falling on a roof", "a man speaking"]
    T = m.embed_text(texts)
    t = np.arange(SR * 4) / float(SR)
    tone = (0.3 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    noise = (np.random.default_rng(0).standard_normal(SR * 8) * 0.2).astype(np.float32)
    A = m.embed_windows([tone, noise])
    top = (A @ T.T).argmax(axis=1).tolist()
    assert [texts[i] for i in top] == ["a high pitched beep tone", "rain falling on a roof"]
    # and the trap: the same text alone and batched with a long one is the same vector
    alone = m.embed_text(["a dog barking"])[0]
    batched = m.embed_text(["a dog barking", "a crowded restaurant at dinner time with "
                            "cutlery and people talking over music"])[0]
    assert float(alone @ batched) > 0.9999
