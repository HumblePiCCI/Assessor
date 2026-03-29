(() => {
  function num(v, d = 0) {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : d;
  }
  function clip(text, limit = 150) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    return clean.length <= limit ? clean : `${clean.slice(0, limit - 1).trim()}…`;
  }
  function splitSentences(text) {
    const parts = String(text || "").split(/(?<=[.!?])\s+/).map(x => x.trim()).filter(Boolean);
    return parts.length ? parts : (text ? [String(text).trim()] : []);
  }
  function pick(sentences, words) {
    for (const s of sentences) {
      const low = s.toLowerCase();
      if (words.some(w => low.includes(w))) return s;
    }
    return sentences.length ? sentences[Math.min(1, sentences.length - 1)] : "";
  }
  function draft(student, index, total, grade, adj) {
    const text = student && student.text ? student.text : "";
    const sents = splitSentences(text);
    const opening = sents[0] || "Your opening introduces a clear direction.";
    const support = pick(sents, ["because", "for example", "according", "evidence", "\"", "%"]) || opening;
    const conv = num(student.conventions_mistake_rate_percent, 0) + num(adj && adj.conventions, 0);
    const wordCount = num(student.word_count, String(text).split(/\s+/).filter(Boolean).length);
    let wish = "";
    if (conv >= 8) {
      wish = `Highest‑leverage next step: do one focused conventions pass (sentence boundaries, punctuation, spelling). Start with: "${clip(opening)}".`;
    } else if (grade < 70) {
      wish = `Highest‑leverage next step: deepen analysis after each example with one "this shows..." sentence. Anchor: "${clip(support)}".`;
    } else if (wordCount < 180) {
      wish = `Highest‑leverage next step: expand your strongest point with one concrete example and one explanation sentence. Build from: "${clip(support)}".`;
    } else {
      wish = `Highest‑leverage next step: tighten thesis precision and link each paragraph back to that thesis. Anchor: "${clip(opening)}".`;
    }
    return {
      star1: `Placement context: rank ${index + 1} of ${total}. Clear strength in idea clarity. Example: "${clip(opening)}".`,
      star2: `Additional strength in support/development. Example: "${clip(support)}".`,
      wish,
    };
  }
  function isFilled(item) {
    return item && (item.star1 || item.star2 || item.wish);
  }
  function generateAll(students, gradeForIndex, adjustments, drafts, force = true) {
    if (!Array.isArray(students)) return;
    students.forEach((s, i) => {
      if (!force && isFilled(drafts[s.student_id])) return;
      drafts[s.student_id] = draft(s, i, students.length, num(gradeForIndex(i), 0), adjustments[s.student_id] || {});
    });
  }
  window.feedbackGenerate = { generateAll };
})();
