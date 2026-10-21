from manimatic.ingest.speech import (latex_to_speech, latex_to_unicode, normalize_asr_word, number_to_words,
                                     tokenize_display, words_of)


def test_numbers():
    assert number_to_words("60") == ["sixty"]
    assert number_to_words("1,234") == ["one", "thousand", "two", "hundred", "thirty", "four"]
    assert number_to_words("3.14") == ["three", "point", "one", "four"]
    assert number_to_words("-5") == ["minus", "five"]


def test_latex_speech():
    assert latex_to_speech(r"60 = 2^2 \cdot 3 \cdot 5") == ["sixty", "equals", "two", "squared", "times", "three",
                                                           "times", "five"]
    assert latex_to_speech(r"\frac{a}{b}") == ["a", "over", "b"]
    assert latex_to_speech(r"\sqrt[3]{x}") == ["cube", "root", "of", "x"]
    assert latex_to_speech(r"x^{n}") == ["x", "to", "the", "n"]


def test_unicode_captions():
    assert latex_to_unicode(r"x^2 + 1") == "x² + 1"
    assert latex_to_unicode(r"2 \cdot 3") == "2 · 3"


def test_same_tokens_both_sides():
    # script and transcript must normalise identically
    assert [t.s for t in tokenize_display("We get $x^2$ and 60%.")] == ["we", "get", "x", "squared", "and", "sixty", "percent"]
    assert normalize_asr_word("x²") == ["x", "squared"]
    assert normalize_asr_word(" 60%,") == ["sixty", "percent"]
    assert words_of("21st-century") == ["twenty", "first", "century"]
    assert words_of("e.g.") == ["for", "example"]


def test_display_carried_on_first_token():
    toks = tokenize_display("Look at 60, for example.")
    assert [(t.s, t.d) for t in toks][:3] == [("look", "Look"), ("at", "at"), ("sixty", "60,")]
