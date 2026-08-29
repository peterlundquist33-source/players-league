// ============================================
// PLAYERS LEAGUE — Grand Entrance Gate
// ESPN/Lake Blue Edition — shown once per session
// ============================================

function checkGate() {
  return sessionStorage.getItem('players_league_gate') === 'true';
}

function showGrandEntrance() {
  const overlay = document.getElementById('gate-overlay');
  overlay.innerHTML = `
    <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0a1628;overflow:hidden;padding:1rem;position:relative;">

      <!-- Subtle grid pattern -->
      <div style="position:absolute;inset:0;background-image:linear-gradient(rgba(0,104,179,0.05) 1px,transparent 1px),linear-gradient(90deg,rgba(0,104,179,0.05) 1px,transparent 1px);background-size:48px 48px;pointer-events:none;"></div>
      <!-- Lake blue glow -->
      <div style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 65%,rgba(0,104,179,0.14) 0%,transparent 65%);pointer-events:none;"></div>

      <div style="text-align:center;position:relative;z-index:1;max-width:460px;width:100%;">
        <style>
          @keyframes pl-fadeUp   { from { opacity:0; transform:translateY(18px); } to { opacity:1; transform:translateY(0); } }
          @keyframes pl-fadeIn   { from { opacity:0; } to { opacity:1; } }
          @keyframes pl-lineGrow { from { width:0; } to { width:100%; } }
          @keyframes pl-statIn   { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }

          .gate-ball   { animation: pl-fadeIn  0.45s ease-out 0s    forwards; opacity:0; }
          .gate-eyebrow{ animation: pl-fadeUp  0.4s  ease-out 0.2s  forwards; opacity:0; }
          .gate-logo   { animation: pl-fadeUp  0.5s  ease-out 0.38s forwards; opacity:0; }
          .gate-sub    { animation: pl-fadeUp  0.4s  ease-out 0.6s  forwards; opacity:0; }
          .gate-divider{ animation: pl-lineGrow 0.55s ease-out 0.75s forwards; }
          .gate-s1     { animation: pl-statIn  0.35s ease-out 0.95s forwards; opacity:0; }
          .gate-s2     { animation: pl-statIn  0.35s ease-out 1.1s  forwards; opacity:0; }
          .gate-s3     { animation: pl-statIn  0.35s ease-out 1.25s forwards; opacity:0; }
          .gate-champs { animation: pl-fadeUp  0.45s ease-out 1.55s forwards; opacity:0; }
          .gate-btn    { animation: pl-fadeUp  0.4s  ease-out 2.0s  forwards; opacity:0; }
          .gate-footer { animation: pl-fadeIn  0.4s  ease-out 2.5s  forwards; opacity:0; }

          .enter-btn {
            padding: 0.75rem 2.6rem;
            background: #0068b3;
            color: #ffffff;
            border: none;
            border-radius: 3px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 0.8rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 2px;
            cursor: pointer;
            transition: all 0.18s ease;
          }
          .enter-btn:hover {
            background: #005292;
            transform: translateY(-1px);
            box-shadow: 0 4px 18px rgba(0,104,179,0.45);
          }
        </style>

        <!-- Football emoji -->
        <div class="gate-ball" style="font-size:3rem;margin-bottom:0.75rem;display:block;line-height:1;">🏈</div>

        <!-- Eyebrow -->
        <div class="gate-eyebrow" style="margin-bottom:0.4rem;">
          <span style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:0.6rem;color:#0068b3;letter-spacing:3px;text-transform:uppercase;font-weight:800;">Est. 2022 &nbsp;&bull;&nbsp; Lake Weekend</span>
        </div>

        <!-- Title -->
        <div class="gate-logo" style="margin-bottom:0.15rem;">
          <h1 style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:clamp(1.9rem,7.5vw,3.4rem);font-weight:900;color:#ffffff;letter-spacing:-0.5px;text-transform:uppercase;line-height:1.05;overflow-wrap:break-word;word-break:break-word;max-width:100%;">PLAYERS LEAGUE</h1>
        </div>

        <!-- Subtitle -->
        <div class="gate-sub" style="margin-bottom:1.4rem;">
          <p style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#c8c8c8;font-size:0.72rem;letter-spacing:2.5px;text-transform:uppercase;">Fantasy Football</p>
        </div>

        <!-- Divider line -->
        <div style="overflow:hidden;max-width:180px;margin:0 auto 1.5rem;height:2px;">
          <div class="gate-divider" style="height:2px;background:linear-gradient(90deg,transparent,#0068b3,transparent);width:0;"></div>
        </div>

        <!-- Stats row -->
        <div style="display:flex;justify-content:center;gap:2.25rem;flex-wrap:wrap;margin-bottom:1.75rem;">
          <div class="gate-s1" style="text-align:center;">
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:1.9rem;font-weight:900;color:#ffffff;line-height:1;">12</div>
            <div style="font-size:0.58rem;color:#a0bcd0;text-transform:uppercase;letter-spacing:1.5px;margin-top:0.2rem;">Teams</div>
          </div>
          <div class="gate-s2" style="text-align:center;">
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:1.9rem;font-weight:900;color:#ffffff;line-height:1;">4</div>
            <div style="font-size:0.58rem;color:#a0bcd0;text-transform:uppercase;letter-spacing:1.5px;margin-top:0.2rem;">Seasons</div>
          </div>
          <div class="gate-s3" style="text-align:center;">
            <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:1.9rem;font-weight:900;color:#ffffff;line-height:1;">0</div>
            <div style="font-size:0.58rem;color:#a0bcd0;text-transform:uppercase;letter-spacing:1.5px;margin-top:0.2rem;">Repeats</div>
          </div>
        </div>

        <!-- Champions row -->
        <div class="gate-champs" style="margin-bottom:2rem;">
          <div style="display:flex;justify-content:center;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.65rem;">
            <div style="background:rgba(0,104,179,0.15);border:1px solid rgba(0,104,179,0.3);border-radius:3px;padding:0.45rem 0.65rem;text-align:center;min-width:86px;">
              <div style="font-size:0.5rem;color:#90bfe0;text-transform:uppercase;letter-spacing:1px;margin-bottom:0.15rem;">2022</div>
              <div style="color:#ffffff;font-weight:800;font-size:0.82rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">🏆 Peter</div>
            </div>
            <div style="background:rgba(0,104,179,0.15);border:1px solid rgba(0,104,179,0.3);border-radius:3px;padding:0.45rem 0.65rem;text-align:center;min-width:86px;">
              <div style="font-size:0.5rem;color:#90bfe0;text-transform:uppercase;letter-spacing:1px;margin-bottom:0.15rem;">2023</div>
              <div style="color:#ffffff;font-weight:800;font-size:0.82rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">🏆 Kaleb</div>
            </div>
            <div style="background:rgba(0,104,179,0.15);border:1px solid rgba(0,104,179,0.3);border-radius:3px;padding:0.45rem 0.65rem;text-align:center;min-width:86px;">
              <div style="font-size:0.5rem;color:#90bfe0;text-transform:uppercase;letter-spacing:1px;margin-bottom:0.15rem;">2024</div>
              <div style="color:#ffffff;font-weight:800;font-size:0.82rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">🏆 Noah</div>
            </div>
            <div style="background:rgba(212,148,58,0.18);border:1px solid rgba(212,148,58,0.5);border-radius:3px;padding:0.45rem 0.65rem;text-align:center;min-width:86px;">
              <div style="font-size:0.5rem;color:#d4943a;text-transform:uppercase;letter-spacing:1px;margin-bottom:0.15rem;">2025</div>
              <div style="color:#d4943a;font-weight:800;font-size:0.82rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">🏆 Adam</div>
            </div>
          </div>
          <p style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#d0d0d0;font-size:0.72rem;font-style:italic;">Four seasons. Four champions. No dynasty yet.</p>
        </div>

        <!-- Enter Button -->
        <div class="gate-btn" style="margin-bottom:1.4rem;">
          <button class="enter-btn" onclick="dismissEntrance()">Enter the League</button>
        </div>

        <!-- Footer whisper -->
        <div class="gate-footer">
          <p style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#b0b0b0;font-size:0.6rem;letter-spacing:2px;text-transform:uppercase;">Draft Smart &bull; Score Big &bull; Take the Belt</p>
        </div>

      </div>
    </div>
  `;
}

function dismissEntrance() {
  sessionStorage.setItem('players_league_gate', 'true');
  var overlay = document.getElementById('gate-overlay');
  overlay.style.transition = 'opacity 0.45s ease';
  overlay.style.opacity = '0';
  setTimeout(function() {
    overlay.remove();
    document.body.style.overflow = '';
  }, 450);
}

// On page load — show grand entrance once per session
if (!checkGate()) {
  document.addEventListener('DOMContentLoaded', function() {
    var overlay = document.createElement('div');
    overlay.id = 'gate-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;';
    document.body.prepend(overlay);
    document.body.style.overflow = 'hidden';
    showGrandEntrance();
  });
}
