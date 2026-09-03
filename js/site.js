// Players League — shared behaviour. Loaded by every page.
// Nav toggle, and the table enhancements the design system leans on:
// numeric columns right-aligned, sortable headers, edge fade on overflow.
(function () {
  "use strict";

  // ---------- nav ----------
  var toggle = document.querySelector(".nav-toggle");
  var links = document.querySelector(".nav-links");
  if (toggle && links) {
    toggle.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && links.classList.contains("open")) {
        links.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  // ---------- tables ----------
  var NUM = /^[\s+\-−–]?\$?\d[\d,]*(\.\d+)?%?\s*$/;   // 12  1,939.3  -4.5  +3.6  61%
  function cellValue(td) {
    var t = (td.textContent || "").replace(/[,%$\s]/g, "").replace(/[−–]/g, "-");
    var n = parseFloat(t);
    return isNaN(n) ? null : n;
  }
  function isNumeric(td) { return NUM.test((td.textContent || "").trim()) && (td.textContent || "").trim() !== ""; }

  function enhance(table) {
    var head = table.tHead && table.tHead.rows[0];
    var body = table.tBodies[0];
    if (!head || !body) return;
    var rows = Array.prototype.slice.call(body.rows);
    var cols = head.cells.length;

    // right-align columns that are mostly numbers (the first column is a label)
    for (var c = 1; c < cols; c++) {
      var n = 0, filled = 0;
      rows.forEach(function (r) {
        var td = r.cells[c]; if (!td) return;
        if ((td.textContent || "").trim()) { filled++; if (isNumeric(td)) n++; }
      });
      if (filled && n / filled >= 0.7) {
        head.cells[c].classList.add("num");
        rows.forEach(function (r) { if (r.cells[c]) r.cells[c].classList.add("num"); });
      }
    }

    // sortable when there's something to sort
    if (rows.length < 4 || table.hasAttribute("data-nosort")) return;
    Array.prototype.forEach.call(head.cells, function (th, idx) {
      if (!(th.textContent || "").trim()) return;
      th.setAttribute("aria-sort", "none");
      th.tabIndex = 0;
      function sort() {
        var dir = th.getAttribute("aria-sort") === "descending" ? "ascending" : "descending";
        Array.prototype.forEach.call(head.cells, function (o) { if (o !== th) o.setAttribute("aria-sort", "none"); });
        th.setAttribute("aria-sort", dir);
        var numeric = th.classList.contains("num");
        var sorted = rows.slice().sort(function (a, b) {
          var ta = a.cells[idx], tb = b.cells[idx];
          if (numeric) {
            var va = cellValue(ta), vb = cellValue(tb);
            if (va === null && vb === null) return 0;
            if (va === null) return 1;
            if (vb === null) return -1;
            return dir === "ascending" ? va - vb : vb - va;
          }
          var sa = (ta.textContent || "").trim().toLowerCase();
          var sb = (tb.textContent || "").trim().toLowerCase();
          return dir === "ascending" ? sa.localeCompare(sb) : sb.localeCompare(sa);
        });
        sorted.forEach(function (r) { body.appendChild(r); });
      }
      th.addEventListener("click", sort);
      th.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sort(); } });
    });
  }

  function markScrollable() {
    document.querySelectorAll(".table-scroll").forEach(function (box) {
      box.classList.toggle("is-scrollable", box.scrollWidth > box.clientWidth + 2);
    });
  }

  function init() {
    document.querySelectorAll("table.data-table").forEach(enhance);
    markScrollable();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
  window.addEventListener("resize", markScrollable);
})();
