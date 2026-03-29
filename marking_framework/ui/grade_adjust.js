(() => {
  function num(v, d = 0) {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : d;
  }
  function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
  }
  function round1(v) {
    return Math.round(v * 10) / 10;
  }
  function confidence(student) {
    const flags = String((student && student.flags) || "").toLowerCase();
    let rubric = clamp(1 - (num(student.rubric_sd_points, 2.5) / 5), 0.2, 1);
    let comparative = clamp(1 - (num(student.rank_sd, 2.5) / 6), 0.2, 1);
    let conventions = clamp(num(student.word_count, 280) / 500, 0.35, 0.9);
    if (flags.includes("rubric")) rubric *= 0.7;
    if (flags.includes("rank")) comparative *= 0.7;
    const total = rubric + comparative + conventions || 1;
    return {
      rubric: rubric / total,
      conventions: conventions / total,
      comparative: comparative / total,
    };
  }
  function distribute(student, delta) {
    const c = confidence(student);
    const rubric = round1(delta * c.rubric);
    const conventions = round1(delta * c.conventions);
    const comparative = round1(delta - rubric - conventions);
    return { rubric, conventions, comparative };
  }
  function resort(students, gradeFor) {
    if (!Array.isArray(students) || typeof gradeFor !== 'function') return;
    const scores = {};
    students.forEach((s, i) => { scores[s.student_id] = num(gradeFor(i), 0); });
    students.sort((a, b) => {
      const diff = scores[b.student_id] - scores[a.student_id];
      if (diff) return diff;
      const comp = num(b.composite_score, 0) - num(a.composite_score, 0);
      if (comp) return comp;
      return String(a.student_id || '').localeCompare(String(b.student_id || ''));
    });
    students.forEach((s, i) => { s.rank = i + 1; });
  }
  window.gradeAdjust = { confidence, distribute, resort };
})();
