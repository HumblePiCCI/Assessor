from pathlib import Path

import scripts.conventions_scan as cs


def test_spelling_errors_count_branches():
    assert cs.spelling_errors_count("Test", None, set()) == 0

    wordlist = {"test", "student", "run"}
    text = "Test 123 a I student's can't"
    # tokens: Test (capitalized -> ignored), 123 (ignored), a (len<3), I (len<3), student's -> student, can't -> can, t
    errors = cs.spelling_errors_count(text, wordlist, set())
    assert errors == 0

    errors2 = cs.spelling_errors_count("Wrongword", wordlist, set())
    assert errors2 == 0

    errors3 = cs.spelling_errors_count("abc123", wordlist, set())
    assert errors3 == 0

    errors4 = cs.spelling_errors_count("'''", wordlist, set())
    assert errors4 == 0


def test_spelling_errors_whitelist_and_unknown_detection():
    wordlist = {"hello"}
    assert cs.spelling_errors_count("hello blorb", wordlist, set()) == 1
    assert cs.spelling_errors_count("hello blorb", wordlist, {"blorb"}) == 0
    wl = cs.build_unknown_whitelist(["blorb one", "blorb two", "other"], wordlist)
    assert "blorb" in wl
    assert cs.build_unknown_whitelist(["anything"], None) == set()
    assert cs._unknown_tokens("123 A Hi Name", {"name"}) == []


def test_load_wordlist_reads_file(tmp_path, monkeypatch):
    fake = tmp_path / "words.txt"
    fake.write_text("Apple\n\nBanana\n", encoding="utf-8")

    orig_exists = cs.Path.exists
    orig_open = cs.Path.open

    def fake_exists(self):
        if str(self) == "/usr/share/dict/words":
            return False
        if str(self) == "/usr/dict/words":
            return True
        return orig_exists(self)

    def fake_open(self, *args, **kwargs):
        if str(self) in ("/usr/share/dict/words", "/usr/dict/words"):
            return orig_open(fake, *args, **kwargs)
        return orig_open(self, *args, **kwargs)

    monkeypatch.setattr(cs.Path, "exists", fake_exists, raising=False)
    monkeypatch.setattr(cs.Path, "open", fake_open, raising=False)
    words = cs.load_wordlist()
    assert "apple" in words
    assert "banana" in words
    other = tmp_path / "other.txt"
    other.write_text("x", encoding="utf-8")
    assert other.exists()
    with other.open("r", encoding="utf-8") as f:
        assert f.read() == "x"


def test_load_wordlist_missing(monkeypatch):
    def fake_exists(self):
        if str(self) in ("/usr/share/dict/words", "/usr/dict/words"):
            return False
        return False

    monkeypatch.setattr(cs.Path, "exists", fake_exists, raising=False)
    words = cs.load_wordlist()
    assert words is None
    assert cs.Path("other").exists() is False


def test_missing_end_punct_count():
    assert cs.missing_end_punct_count("Hello world.") == 0
    assert cs.missing_end_punct_count("Hello world") == 1


def test_conventions_scan_main(tmp_path, monkeypatch):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "s1.txt").write_text("hello world", encoding="utf-8")
    out_path = tmp_path / "out.csv"

    monkeypatch.setattr(cs, "load_wordlist", lambda: {"hello", "world"})
    monkeypatch.setattr("sys.argv", ["cs", "--inputs", str(input_dir), "--output", str(out_path)])
    assert cs.main() == 0
    assert out_path.exists()

    # Require wordlist but none found
    monkeypatch.setattr(cs, "load_wordlist", lambda: None)
    monkeypatch.setattr("sys.argv", ["cs", "--inputs", str(input_dir), "--output", str(out_path), "--require-wordlist"])
    assert cs.main() == 1


def test_conventions_scan_main_empty(tmp_path, monkeypatch):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    out_path = tmp_path / "out.csv"
    monkeypatch.setattr(cs, "load_wordlist", lambda: {"hello"})
    monkeypatch.setattr("sys.argv", ["cs", "--inputs", str(input_dir), "--output", str(out_path)])
    assert cs.main() == 0
