#!/usr/bin/env python3
import argparse
import csv
import logging
import re
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_wordlist():
    for path in ("/usr/share/dict/words", "/usr/dict/words"):
        p = Path(path)
        if p.exists():
            logger.info(f"Using wordlist: {p}")
            words = set()
            with p.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    w = line.strip().lower()
                    if w:
                        words.add(w)
            return words
    logger.warning("No system wordlist found; spelling check will be skipped")
    return None


def sentence_start_lowercase_count(text: str) -> int:
    return len(re.findall(r"(?:^|[.!?]\s+)([a-z])", text))


def missing_end_punct_count(text: str) -> int:
    count = 0
    for para in [p for p in text.split("\n\n") if p.strip()]:
        if para and para[-1] not in ".!?":
            count += 1
    return count


def repeated_spaces_count(text: str) -> int:
    return text.count("  ")


def _token_parts(token: str) -> list[str]:
    tok_clean = token.lower().strip("'")
    if tok_clean.endswith("'s"):
        tok_clean = tok_clean[:-2]
    parts = [p for p in tok_clean.split("'") if p]
    if any(len(part) == 1 for part in parts):
        return []
    return parts


def _unknown_tokens(text: str, wordlist) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9']+", text)
    out = []
    for tok in tokens:
        if any(ch.isdigit() for ch in tok):
            continue
        if len(tok) < 3:
            continue
        # Treat title-case tokens as likely proper nouns.
        if tok[0].isupper() and tok[1:].islower():
            continue
        for part in _token_parts(tok):
            if part not in wordlist:
                out.append(part)
    return out


def build_unknown_whitelist(texts: list[str], wordlist) -> set[str]:
    if wordlist is None:
        return set()
    counts = {}
    for text in texts:
        seen = set(_unknown_tokens(text, wordlist))
        for token in seen:
            counts[token] = counts.get(token, 0) + 1
    # Unknown words repeated across multiple submissions are often names or domain terms.
    return {token for token, count in counts.items() if count >= 2}


def spelling_errors_count(text: str, wordlist, unknown_whitelist=None) -> int:
    if wordlist is None:
        return 0
    unknown_whitelist = unknown_whitelist or set()
    tokens = re.findall(r"[A-Za-z0-9']+", text)
    errors = 0
    for tok in tokens:
        if any(ch.isdigit() for ch in tok):
            continue
        if len(tok) < 3:
            continue
        # Treat title-case tokens as likely proper nouns.
        if tok[0].isupper() and tok[1:].islower():
            continue
        for part in _token_parts(tok):
            if part in unknown_whitelist:
                continue
            if part not in wordlist:
                errors += 1
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, help="Directory of normalized .txt files")
    parser.add_argument("--output", required=True, help="CSV output path")
    parser.add_argument("--require-wordlist", action="store_true", help="Fail if no system wordlist found")
    args = parser.parse_args()

    wordlist = load_wordlist()
    if args.require_wordlist and wordlist is None:
        logger.error("Wordlist required but not found. Aborting.")
        return 1
    in_dir = Path(args.inputs)
    rows = []
    texts_by_path = {
        path: path.read_text(encoding="utf-8", errors="ignore")
        for path in sorted(in_dir.glob("*.txt"))
    }
    unknown_whitelist = build_unknown_whitelist(list(texts_by_path.values()), wordlist)

    for path in sorted(texts_by_path):
        text = texts_by_path[path]
        words = re.findall(r"[A-Za-z']+", text)
        word_count = len(words)

        spelling_errors = spelling_errors_count(text, wordlist, unknown_whitelist=unknown_whitelist)
        lower_starts = sentence_start_lowercase_count(text)
        missing_end = missing_end_punct_count(text)
        repeated_spaces = repeated_spaces_count(text)

        total_errors = spelling_errors + lower_starts + missing_end + repeated_spaces
        mistake_rate = (total_errors / word_count) if word_count else 0.0

        rows.append(
            {
                "student_id": path.stem.strip(),
                "word_count": word_count,
                "spelling_errors": spelling_errors,
                "sentence_start_lowercase": lower_starts,
                "missing_end_punct": missing_end,
                "repeated_spaces": repeated_spaces,
                "total_errors": total_errors,
                "mistake_rate_percent": round(mistake_rate * 100, 2),
                "wordlist_used": "yes" if wordlist else "no",
            }
        )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
