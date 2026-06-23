// Grade adjustment moved to server-authoritative pin & re-flow.
// The server endpoint /projects/curve/reflow owns all curve math; app.js
// keeps only pins + the last re-flow response. This file remains for the
// served-asset contract and exposes a tiny ordering helper.
(() => {
  function applyOrder(students, orderedIds) {
    if (!Array.isArray(students) || !Array.isArray(orderedIds)) return students;
    const byId = new Map(students.map(s => [s.student_id, s]));
    const ordered = orderedIds.map(id => byId.get(id)).filter(Boolean);
    if (ordered.length !== students.length) return students;
    ordered.forEach((s, i) => { s.rank = i + 1; });
    return ordered;
  }
  window.gradeAdjust = { applyOrder };
})();
