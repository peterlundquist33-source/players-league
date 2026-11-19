/* Beat the Board — CHANNEL 11.
   The only page on this site that writes. Everything it needs to know about the
   week (slate, lock time, the twelve names, the featured player) is baked into
   window.BOARD by tools/board.py; the live part is Firestore, same project and
   same no-accounts trust model as the pick'em and the wedding to-do list.

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

  // The week's featured player, or null if none could be drawn. When it's null
  // there is nothing to predict, so the card carries pred 0 and the page says
  // the bonus is off — the slate still scores normally.
  var FEAT = B.featured || null;
  var CAP = B.predCap || 100;

  var db = null;
  var state = {
    me: "",
    picks: {},          // matchupId -> winner first name
    conf: {},           // matchupId -> "1".."6"
    pred: "",           // predicted full-PPR total for the featured player
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
    state.pred = entry.pred == null ? "" : String(entry.pred);
  }

  // Strict on purpose: parseFloat("12abc") is 12, which would quietly file a
  // number nobody typed. Only a plain decimal counts.
  function predValue() {
    var raw = String(state.pred).trim();
    if (!/^\d+(\.\d+)?$/.test(raw)) return null;
    var v = Number(raw);
    return isFinite(v) ? v : null;
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
    if (FEAT) {
      var p = predValue();
      if (p === null) {
        out.push("Enter " + FEAT.name + "'s full-PPR total — a number, to a tenth.");
      } else if (p > CAP) {
        out.push("That prediction is over " + CAP + " — nobody scores that.");
      }
    }
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
      // No featured player means nothing to predict, but the rules still
      // require the field, so a tiebreaker-less week files a flat 0.
      pred: FEAT ? predValue() : 0,
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
      " using each number once. 1 is your shakiest call, " + MAX + " your surest." +
      (FEAT ? " Then call " + FEAT.name + "'s full-PPR total for the tiebreaker." : "")));
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
      var opts = el("div", "bd-conf-opts");
      opts.setAttribute("role", "group");
      opts.setAttribute("aria-label", "Confidence rank for " + g.away + " at " + g.home);
      RANKS.forEach(function (r) {
        var mine = state.conf[g.id] === r;
        // Which other matchup, if any, is already holding this rank.
        var heldBy = null;
        Object.keys(state.conf).forEach(function (k) {
          if (k !== g.id && state.conf[k] === r) heldBy = k;
        });
        var cls = "bd-rank" + (mine ? " is-on" : "") + (!mine && heldBy ? " is-taken" : "");
        var rb = el("button", cls, r);
        rb.type = "button";
        rb.setAttribute("aria-pressed", mine ? "true" : "false");
        rb.setAttribute("aria-label", "Rank " + r + " of " + MAX);
        rb.addEventListener("click", function () {
          if (mine) {
            delete state.conf[g.id];
          } else if (heldBy) {
            // Ranks are a permutation, so trade with the matchup that holds it
            // instead of creating a duplicate.
            var prev = state.conf[g.id];
            if (prev) state.conf[heldBy] = prev; else delete state.conf[heldBy];
            state.conf[g.id] = r;
          } else {
            state.conf[g.id] = r;
          }
          state.msg = "";
          render();
        });
        opts.appendChild(rb);
      });
      cw.appendChild(opts);
      row.appendChild(cw);
      f.appendChild(row);
    });

    // the one tiebreaker — the featured player's full-PPR total
    var tb = el("div", "bd-field");
    if (FEAT) {
      tb.appendChild(el("span", "bd-label", FEAT.name));
      var inp = el("input", "bd-input");
      inp.type = "number";
      inp.step = "0.1";
      inp.min = "0";
      inp.max = String(CAP);
      inp.value = state.pred;
      inp.setAttribute("aria-label", FEAT.name + " full-PPR points");
      inp.addEventListener("input", function () {
        state.pred = inp.value;
        state.msg = "";
      });
      tb.appendChild(inp);
      var where = (FEAT.home ? "vs " : "at ") + FEAT.opp;
      tb.appendChild(el("span", "bd-hint",
        "His full-PPR points this week, to a tenth" +
        (FEAT.opp ? " — " + FEAT.team + " " + where : "") +
        (FEAT.kickoffLabel ? ", " + FEAT.kickoffLabel : "")));
    } else {
      tb.appendChild(el("span", "bd-label", "Tiebreaker"));
      tb.appendChild(el("span", "bd-hint",
        "No featured player this week, so there's nothing to call — the slate scores on its own."));
    }
    f.appendChild(tb);

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
    hr.appendChild(el("th", null, "Guess"));
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
      tr.appendChild(el("td", "muted", e.pred == null ? "—" : String(e.pred)));
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
