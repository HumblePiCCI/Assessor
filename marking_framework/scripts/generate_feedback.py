#!/usr/bin/env python3
"""
Generate "Two Stars and a Wish" feedback for each student.

This script:
1. Loads final grades from grade_curve.csv
2. Loads student texts from normalized_text/
3. Generates structured feedback with quote validation
4. Outputs per-student feedback files

Requirements:
- Run AFTER review_and_grade.py (needs final grades)
- Needs original student text files
- Optionally uses LLM for automated feedback generation
"""
import argparse
import csv
import json
import logging
import re
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_student_text(student_id: str, texts_dir: Path) -> str:
    """Load the normalized text for a student."""
    text_file = texts_dir / f"{student_id}.txt"
    if not text_file.exists():
        logger.warning(f"Text file not found for student '{student_id}': {text_file}")
        return ""
    return text_file.read_text(encoding="utf-8", errors="ignore")


def validate_quote(quote: str, text: str, context_chars: int = 100) -> dict:
    """
    Validate that a quote appears in the text.
    
    Returns:
        dict with:
        - valid: bool
        - exact_match: bool
        - fuzzy_match: bool
        - context: surrounding text if found
        - suggestion: corrected quote if fuzzy match
    """
    # Normalize whitespace for comparison
    quote_normalized = " ".join(quote.split())
    text_normalized = " ".join(text.split())
    
    # Try exact match
    if quote_normalized in text_normalized:
        # Find context
        idx = text_normalized.index(quote_normalized)
        start = max(0, idx - context_chars)
        end = min(len(text_normalized), idx + len(quote_normalized) + context_chars)
        context = text_normalized[start:end]
        
        return {
            "valid": True,
            "exact_match": True,
            "fuzzy_match": False,
            "context": f"...{context}...",
            "suggestion": None
        }
    
    # Try fuzzy match (allowing minor punctuation/capitalization differences)
    quote_alpha = re.sub(r'[^\w\s]', '', quote_normalized.lower())
    
    # Search for sequences of 5+ words from the quote
    quote_words = quote_alpha.split()
    if len(quote_words) >= 5:
        # Try to find the first 5 words
        search_phrase = " ".join(quote_words[:5])
        text_alpha = re.sub(r'[^\w\s]', '', text_normalized.lower())
        
        if search_phrase in text_alpha:
            idx = text_alpha.index(search_phrase)
            # Find the actual text at this position
            # Count words to get approximate position
            words_before = len(text_alpha[:idx].split())
            text_words = text_normalized.split()
            
            # Extract surrounding words
            start_word = max(0, words_before - 5)
            end_word = min(len(text_words), words_before + len(quote_words) + 5)
            suggestion = " ".join(text_words[words_before:words_before + len(quote_words)])
            context = " ".join(text_words[start_word:end_word])
            
            return {
                "valid": True,
                "exact_match": False,
                "fuzzy_match": True,
                "context": f"...{context}...",
                "suggestion": suggestion
            }
    
    return {
        "valid": False,
        "exact_match": False,
        "fuzzy_match": False,
        "context": None,
        "suggestion": "Quote not found in text"
    }


def generate_manual_feedback_template(student_id: str, grade: int, text: str) -> str:
    """
    Generate a template for manual feedback creation.
    """
    # Extract first few sentences as a preview
    sentences = re.split(r'[.!?]+', text)
    preview = '. '.join(sentences[:3])[:300] + "..."
    
    template = f"""# Two Stars and a Wish: {student_id}

**Final Grade:** {grade}

## Text Preview
{preview}

## Two Stars (Strengths)

### Star 1
**Strength:** [Describe what the student did well - be specific]

**Quote:**
> "[Paste exact quote from student's text that demonstrates this strength]"

**Explanation:** [Why this is a strength and how it contributes to the essay's quality]

### Star 2
**Strength:** [Describe another strength - choose the second-most important positive aspect]

**Quote:**
> "[Paste exact quote from student's text that demonstrates this strength]"

**Explanation:** [Why this is a strength]

## One Wish (Highest-Leverage Improvement)

**Wish:** [Describe the single most important thing the student should improve]

**Quote showing the gap:**
> "[Paste exact quote from student's text that demonstrates where improvement is needed]"

**Explanation:** [Why fixing this would most improve the essay's overall quality. Be constructive and specific about what to do differently]

---
Generated: {Path(__file__).name}
"""
    return template


def generate_feedback_batch(grades_csv: Path, texts_dir: Path, output_dir: Path, 
                            validate_only: bool = False):
    """
    Generate feedback for all students.
    
    Args:
        grades_csv: Path to grade_curve.csv
        texts_dir: Path to normalized text directory
        output_dir: Path to output directory for feedback files
        validate_only: If True, only validate existing feedback files
    """
    # Load grades
    logger.info(f"Loading grades from {grades_csv}")
    with grades_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        grades = {row["student_id"]: row for row in reader}
    
    logger.info(f"Loaded grades for {len(grades)} students")
    
    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each student
    validation_errors = []
    
    for student_id, grade_row in sorted(grades.items()):
        final_grade = int(grade_row.get("final_grade", 0))
        
        # Load student text
        text = load_student_text(student_id, texts_dir)
        if not text:
            logger.error(f"Cannot generate feedback for '{student_id}': text not found")
            validation_errors.append(f"{student_id}: missing text file")
            continue
        
        output_file = output_dir / f"{student_id}_feedback.md"
        
        if validate_only:
            # Validate existing feedback
            if not output_file.exists():
                logger.warning(f"Feedback file missing: {output_file}")
                validation_errors.append(f"{student_id}: feedback file not found")
                continue
            
            # Parse and validate quotes
            feedback_text = output_file.read_text(encoding="utf-8")
            
            # Extract quotes (look for markdown blockquotes)
            quotes = re.findall(r'>\s*"([^"]+)"', feedback_text)
            
            if len(quotes) < 3:
                logger.warning(f"{student_id}: Found only {len(quotes)} quotes, expected at least 3")
                validation_errors.append(f"{student_id}: insufficient quotes ({len(quotes)}/3)")
            
            # Validate each quote
            for idx, quote in enumerate(quotes, 1):
                validation = validate_quote(quote, text)
                if not validation["valid"]:
                    logger.error(f"{student_id} quote #{idx} INVALID: '{quote[:50]}...'")
                    validation_errors.append(f"{student_id}: quote #{idx} not found in text")
                elif validation["fuzzy_match"]:
                    logger.warning(f"{student_id} quote #{idx} fuzzy match (check punctuation)")
                else:
                    logger.info(f"{student_id} quote #{idx} ✓ valid")
        
        else:
            # Generate new feedback template
            if output_file.exists():
                logger.info(f"Skipping {student_id}: feedback already exists")
                continue
            
            template = generate_manual_feedback_template(student_id, final_grade, text)
            output_file.write_text(template, encoding="utf-8")
            logger.info(f"✓ Generated template for {student_id}")
    
    # Report validation results
    if validation_errors:
        logger.error(f"\n{'='*60}")
        logger.error(f"VALIDATION FAILED: {len(validation_errors)} error(s)")
        logger.error(f"{'='*60}")
        for error in validation_errors[:20]:
            logger.error(f"  - {error}")
        if len(validation_errors) > 20:
            logger.error(f"  ... and {len(validation_errors) - 20} more")
        return 1
    else:
        logger.info(f"\n{'='*60}")
        logger.info("✓ All validations passed")
        logger.info(f"{'='*60}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate 'Two Stars and a Wish' feedback for students"
    )
    parser.add_argument(
        "--grades",
        default="outputs/grade_curve.csv",
        help="Path to grade_curve.csv"
    )
    parser.add_argument(
        "--texts",
        default="processing/normalized_text",
        help="Directory containing student text files"
    )
    parser.add_argument(
        "--output",
        default="outputs/feedback_summaries",
        help="Output directory for feedback files"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate existing feedback files instead of generating new ones"
    )
    args = parser.parse_args()
    
    grades_path = Path(args.grades)
    texts_path = Path(args.texts)
    output_path = Path(args.output)
    
    # Validate inputs
    if not grades_path.exists():
        logger.error(f"Grades file not found: {grades_path}")
        logger.error("Run review_and_grade.py first to generate final grades")
        return 1
    
    if not texts_path.exists():
        logger.error(f"Texts directory not found: {texts_path}")
        logger.error("Run extract_text.py first to normalize student submissions")
        return 1
    
    # Generate or validate
    return generate_feedback_batch(
        grades_path, 
        texts_path, 
        output_path,
        validate_only=args.validate
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
