"""Japanese is not Chinese, even though it is written partly in kanji.

`needs_translation` used to count only CJK ideographs, so any Japanese sentence
whose kanji share cleared 15% was treated as "already Chinese" and never
translated. Found 2026-10-09 on a real clip: a Japanese transcript of 2,287
segments had translations for 598 of them -- only the kana-heavy lines, where
the kanji share happened to fall under the threshold. The rest were skipped
silently; `failed` stayed 0, so the run looked complete.
"""
from __future__ import annotations

import pytest

from reel_scout import translate


@pytest.mark.parametrize("text", [
    "このケーブルは音質がすごく良いです",
    "電源ケーブルの交換で音場が広がる",
    "スキー場の雪質は最高でした",
    "今日はとても良い天気ですね。東京に行きました。",
])
def test_japanese_with_kanji_is_still_translated(text):
    assert translate.cjk_ratio(text) > translate.CJK_ALREADY  # the old trap
    assert translate.needs_translation(text) is True


@pytest.mark.parametrize("text", [
    "這是一段中文描述，講的是鏡頭裡有什麼",
    "这是一段简体中文的描述",
    # Taiwan copy borrows a stray の for flavour; one kana does not make it Japanese.
    "職人の手工皮件，台灣製造",
])
def test_chinese_stays_untranslated(text):
    assert translate.needs_translation(text) is False


def test_mostly_kanji_japanese_is_left_alone():
    # No kana at all reads as Chinese and is legible to a Chinese reader anyway;
    # this pins that the fix keys on kana, not on guessing.
    assert translate.needs_translation("東京都渋谷区") is False


# Review follow-up (2026-10-09): the katakana middle dot and the long-vowel
# mark are punctuation in Chinese copy, not evidence of Japanese.
@pytest.mark.parametrize("text", [
    "哈利・波特・妙麗",
    "台北ー高雄ー台中",
    "林・陳・王三位老師ー現場示範",
])
def test_chinese_using_japanese_punctuation_is_not_japanese(text):
    from reel_scout.translate import needs_translation
    assert needs_translation(text) is False


def test_japanese_with_those_marks_is_still_japanese():
    from reel_scout.translate import needs_translation
    assert needs_translation("スーパー・マーケットで買いました") is True
    assert needs_translation("ラーメン屋の店主") is True
