/* Beat the Board — CHANNEL 11.
   The only page on this site that writes. Everything it needs to know about the
   week (slate, lock time, the twelve names) is baked into window.BOARD by
   tools/board.py; the live part is Firestore, same project and same
   no-accounts trust model as the pick'em and the wedding to-do list.

   The leaderboard is NOT scored here — tools/board.py owns the math and bakes
   it into the page. This file only collects a card and shows who has filed one. */
(function () {
  "use strict";

  var B = window.BOARD;
  if (!B) return;
  var live = document.getElementById("bd-live");
  var MAX = B.maxConf;
  var RANKS = [];
  for (var i = 1; i <= MAX; i++) RANKS.push(String(i));

  var db = null;
  var state = {
    me: "",
    picks: {},          // matchupId -> winner first name
    conf: {},           // matchupId -> "1".."6"
    high: "",
    margin: "",
    entries: {},        // owner full name -> entry, this week, live
    msg: "",
    msgKind: "",
    saving: false
  };

  // The lock is the one thing the browser must not get to decide: the same
  // millisecond value is compiled into the Firestore rules, so a fiddled clock
  // only changes what this page shows, never what the database accepts.
  function locked() { return !B.lockMs || Date.now() >= B.lockMs; }

  function docId(owner) { return B.week + "-" + owner; }

  /* ------------------------------------------------------------- countdown */
  function tick() {
    var el = document.getElementById("bd-clock");
    var chip = document.getElementById("bd-chip");
    var box = document.getElementById("bd-state");
    if (!el) return;
    var left = B.lockMs - Date.now();
    if (left <= 0) {
      el.textContent = "Locked";
      if (box) box.classList.add("is-locked");
      if (chip) chip.textContent = "Week " + B.week + " · final";
      return;
    }
    var s = Math.floor(left / 1000), d = Math.floor(s / 86400);
    var h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    el.textContent = (d ? d + "d " : "") + h + "h " + m + "m to pick";
  }

  /* --------------------------------------------------------------- storage */
  function start() {
    try {
      if (window.firebase && window.FIREBASE_CONFIG) {
        firebase.initializeApp(window.FIREBASE_CONFIG);
        db = firebase.firestore();
      }
    } catch (e) { db = null; }
    if (!db) {
      state.msg = "Can't reach the database — nothing can be saved right now. Reload to retry.";
      state.msgKind = "bad";
      render();
      return;
    }
    // Rebuild from the snapshot rather than merging, so a card someone
    // overwrote never lingers on another screen.
    db.collection(B.collection).onSnapshot(function (snap) {
      state.entries = {};
      snap.docs.forEach(function (d) {
        var v = d.data();
        if (!v || String(v.week) !== String(B.week)) return;
        state.entries[v.owner] = v;
      });
      if (state.me && state.entries[state.me] && !state.saving) adopt(state.entries[state.me]);
      render();
    }, function () {
      state.msg = "Lost the live connection to the database.";
      state.msgKind = "bad";
      render();
    });
  }

  function adopt(entry) {
    state.picks = {};
    state.conf = {};
    B.games.forEach(function (g) {
      if (entry.picks && entry.picks[g.id]) state.picks[g.id] = entry.picks[g.id];
      if (entry.conf && entry.conf[g.id]) state.conf[g.id] = String(entry.conf[g.id]);
    });
    state.high = entry.high == null ? "" : String(entry.high);
    state.margin = entry.margin == null ? "" : String(entry.margin);
  }

  /* ------------------------------------------------------------ validation */
  // Returns a list of human problems. Empty list = submittable. The same three
  // shape rules are enforced again in firestore.rules; this copy exists to say
  // *which* rank is doubled up, which a rejected write can't tell you.
  function problems() {
    var out = [];
    if (!state.me) out.push("Pick your name first.");
    var missing = B.games.filter(function (g) { return !state.picks[g.id]; });
    if (missing.length) out.push(missing.length + " matchup" + (missing.length > 1 ? "s" : "") + " still unpicked.");
    var used = {}, dupes = [], blank = 0;
    B.games.forEach(function (g) {
      var c = state.conf[g.id];
      if (!c) { blank++; return; }
      used[c] = (used[c] || 0) + 1;
    });
    Object.keys(used).forEach(function (c) { if (used[c] > 1) dupes.push(c); });
    if (blank) out.push(blank + " confidence rank" + (blank > 1 ? "s" : "") + " not set.");
    if (dupes.length) {
      dupes.sort();
      out.push("Rank " + dupes.join(" and ") + " used more than once — each of 1 to " + MAX + " exactly once.");
    }
    if (!(parseFloat(state.high) > 0)) out.push("Enter a predicted highest team score.");
    if (!(parseFloat(state.margin) >= 0)) out.push("Enter a predicted smallest margin.");
    return out;
  }

  function dupeRanks() {
    var used = {}, bad = {};
    B.games.forEach(function (g) {
      var c = state.conf[g.id];
      if (c) used[c] = (used[c] || 0) + 1;
    });
    B.games.forEach(function (g) {
      var c = state.conf[g.id];
      if (c && used[c] > 1) bad[g.id] = true;
    });
    return bad;
  }

  /* ---------------------------------------------------------------- submit */
  function submit() {
    var errs = problems();
    if (errs.length) {
      state.msg = errs.join(" ");
      state.msgKind = "bad";
      render();
      return;
    }
    if (locked()) {
      state.msg = "Too late — this week locked at kickoff.";
      state.msgKind = "bad";
      render();
      return;
    }
    if (!db) return;
    var conf = {};
    Object.keys(state.conf).forEach(function (k) { conf[k] = String(state.conf[k]); });
    var payload = {
      week: String(B.week),
      owner: state.me,
      picks: state.picks,
      conf: conf,
      high: parseFloat(state.high),
      margin: parseFloat(state.margin),
      updated: firebase.firestore.FieldValue.serverTimestamp()
    };
    state.saving = true;
    state.msg = "Saving…";
    state.msgKind = "";
    render();
    db.collection(B.collection).doc(docId(state.me)).set(payload).then(function () {
      state.saving = false;
      state.msg = "Card filed for Week " + B.week + ". Resubmit any time before the lock.";
      state.msgKind = "good";
      render();
    }).catch(function (e) {
      state.saving = false;
      // A rules rejection here means the lock passed between load and submit,
      // or the card was malformed — the database, not this page, has the say.
      state.msg = (e && e.code === "permission-denied")
        ? "The database refused that card. Either Week " + B.week + " just locked, or the entry didn't pass the rules."
        : "Couldn't save: " + ((e && e.message) || "unknown error");
      state.msgKind = "bad";
      render();
    });
  }

  /* ---------------------------------------------------------------- render */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function tracker() {
    var wrap = el("div");
    var inCount = 0;
    B.entrants.forEach(function (o) { if (state.entries[o]) inCount++; });
    var head = el("p", "section-sub",
      inCount + " of " + B.entrants.length + " have filed a card for Week " + B.week + ".");
    wrap.appendChild(head);
    var row = el("div", "bd-who");
    B.entrants.forEach(function (o) {
      var short = o.split(" ")[0];
      if (short.toLowerCase() === "cj") short = "CJ";
      var s = el("span", state.entries[o] ? "is-in" : "is-out", short);
      s.title = state.entries[o] ? o + " — in" : o + " — nothing yet";
      row.appendChild(s);
    });
    wrap.appendChild(row);
    return wrap;
  }

  function form() {
    var f = el("section", "bd-form");
    var head = el("header");
    head.appendChild(el("h2", null, "Your card — Week " + B.week));
    head.appendChild(el("p", null,
      "Pick a winner in all " + B.games.length + ", then rank every matchup 1 to " + MAX +
      " using each number once. 1 is your shakiest call, " + MAX + " your surest."));
    f.appendChild(head);

    // who
    var who = el("div", "bd-field");
    who.appendChild(el("span", "bd-label", "Who are you"));
    var sel = el("select", "bd-select");
    sel.id = "bd-me";
    var ph = el("option", null, "Choose your name…");
    ph.value = "";
    sel.appendChild(ph);
    B.entrants.forEach(function (o) {
      var op = el("option", null, o + (state.entries[o] ? "  ✓ filed" : ""));
      op.value = o;
      if (o === state.me) op.selected = true;
      sel.appendChild(op);
    });
    sel.addEventListener("change", function () {
      state.me = sel.value;
      try { localStorage.setItem("pl.board.me", state.me); } catch (e) {}
      if (state.entries[state.me]) {
        adopt(state.entries[state.me]);
        state.msg = "Loaded the card you already filed. Change anything and resubmit.";
        state.msgKind = "";
      } else {
        state.msg = "";
        state.msgKind = "";
      }
      render();
    });
    who.appendChild(sel);
    who.appendChild(el("span", "bd-hint", "No free text — the list is the list."));
    f.appendChild(who);

    // games
    var bad = dupeRanks();
    B.games.forEach(function (g) {
      var row = el("div", "bd-game");
      var sides = el("div", "bd-sides");
      [["away", g.away, g.awayTeam], ["home", g.home, g.homeTeam]].forEach(function (pair) {
        var btn = el("button", "bd-side" + (state.picks[g.id] === pair[1] ? " is-on" : ""));
        btn.type = "button";
        btn.setAttribute("aria-pressed", state.picks[g.id] === pair[1] ? "true" : "false");
        var own = el("span", "bd-side-own", pair[1]);
        btn.appendChild(own);
        btn.appendChild(el("span", "bd-side-team", pair[2] || ""));
        btn.addEventListener("click", function () {
          state.picks[g.id] = pair[1];
          state.msg = "";
          render();
        });
        sides.appendChild(btn);
      });
      row.appendChild(sides);

      var cw = el("div", "bd-conf" + (bad[g.id] ? " is-dupe" : ""));
      cw.appendChild(el("span", "bd-label", "Confidence"));
      var cs = el("select");
      cs.setAttribute("aria-label", "Confidence rank for " + g.away + " at " + g.home);
      var blank = el("option", null, "—");
      blank.value = "";
      cs.appendChild(blank);
      RANKS.forEach(function (r) {
        var op = el("option", null, r);
        op.value = r;
        if (state.conf[g.id] === r) op.selected = true;
        cs.appendChild(op);
      });
      cs.addEventListener("change", function () {
        if (cs.value) state.conf[g.id] = cs.value; else delete state.conf[g.id];
        state.msg = "";
        render();
      });
      cw.appendChild(cs);
      row.appendChild(cw);
      f.appendChild(row);
    });

    // tiebreakers
    [["high", "Highest team score", "Any one team's best total this week", "0.1"],
     ["margin", "Smallest margin", "The week's closest game, in points", "0.1"]
    ].forEach(function (t) {
      var row = el("div", "bd-field");
      row.appendChild(el("span", "bd-label", t[1]));
      var inp = el("input", "bd-input");
      inp.type = "number";
      inp.step = t[3];
      inp.min = "0";
      inp.value = state[t[0]];
      inp.setAttribute("aria-label", t[1]);
      inp.addEventListener("input", function () {
        state[t[0]] = inp.value;
        state.msg = "";
      });
      row.appendChild(inp);
      row.appendChild(el("span", "bd-hint", t[2]));
      f.appendChild(row);
    });

    // actions
    var act = el("div", "bd-actions");
    var go = el("button", "btn", state.entries[state.me] ? "Resubmit card" : "File card");
    go.type = "button";
    if (state.saving) go.disabled = true;
    go.addEventListener("click", submit);
    act.appendChild(go);
    if (state.msg) act.appendChild(el("span", "bd-msg" + (state.msgKind ? " is-" + state.msgKind : ""), state.msg));
    f.appendChild(act);
    return f;
  }

  function cardsTable() {
    var owners = B.entrants.filter(function (o) { return state.entries[o]; });
    if (!owners.length) {
      return el("p", "bd-empty", "Nobody filed a card for Week " + B.week + ". A clean sheet, and not the good kind.");
    }
    var scroll = el("div", "table-scroll");
    var t = el("table", "data-table sticky-first bd-grid");
    var thead = el("thead"), hr = el("tr");
    hr.appendChild(el("th", null, "Owner"));
    B.games.forEach(function (g) { hr.appendChild(el("th", null, g.away + " / " + g.home)); });
    hr.appendChild(el("th", null, "High"));
    hr.appendChild(el("th", null, "Margin"));
    thead.appendChild(hr);
    t.appendChild(thead);
    var tb = el("tbody");
    owners.forEach(function (o) {
      var e = state.entries[o], tr = el("tr");
      var name = o.split(" ")[0];
      if (name.toLowerCase() === "cj") name = "CJ";
      tr.appendChild(el("td", "strong", name));
      B.games.forEach(function (g) {
        var td = el("td");
        var pick = (e.picks || {})[g.id] || "—";
        var c = (e.conf || {})[g.id];
        td.appendChild(el("span", "bd-pick", pick));
        if (c) {
          var tag = el("span", "bd-conf-cell", "  " + c);
          td.appendChild(tag);
        }
        tr.appendChild(td);
      });
      tr.appendChild(el("td", "muted", e.high == null ? "—" : String(e.high)));
      tr.appendChild(el("td", "muted", e.margin == null ? "—" : String(e.margin)));
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    scroll.appendChild(t);
    return scroll;
  }

  function render() {
    if (!live) return;
    live.textContent = "";
    var sec = el("section", "section");
    sec.style.paddingLeft = "0";
    sec.style.paddingRight = "0";

    if (!B.games.length) {
      sec.appendChild(el("span", "eyebrow", "Standby"));
      sec.appendChild(el("h2", "section-title", "No slate yet"));
      sec.appendChild(el("p", "section-sub",
        "Week " + B.week + "'s matchups post with the Wednesday preview. Check back then."));
      live.appendChild(sec);
      return;
    }

    if (locked()) {
      sec.appendChild(el("span", "eyebrow", "Week " + B.week));
      sec.appendChild(el("h2", "section-title", "Everyone's card"));
      sec.appendChild(el("p", "section-sub",
        "Week " + B.week + " is locked. Picks are shown with the confidence rank each owner put on them."));
      sec.appendChild(cardsTable());
      sec.appendChild(tracker());
    } else {
      sec.appendChild(form());
      var t = el("section", "section");
      t.style.paddingLeft = "0";
      t.style.paddingRight = "0";
      t.appendChild(el("span", "eyebrow", "Week " + B.week));
      t.appendChild(el("h2", "section-title", "Who's in"));
      t.appendChild(tracker());
      live.appendChild(sec);
      live.appendChild(t);
      return;
    }
    live.appendChild(sec);
  }

  try {
    var saved = localStorage.getItem("pl.board.me");
    if (saved && B.entrants.indexOf(saved) >= 0) state.me = saved;
  } catch (e) {}

  render();
  tick();
  setInterval(tick, 30000);
  start();
})();
