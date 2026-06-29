/** Modal reference for the rmscript language, shown from the Behaviors editor.
 * Content ported from the Reachy Mini Coding Lab guide, with sections added for
 * this app's picture/play/pause commands and the tool-description first line. */

import { h } from "../ui.js";

// The guide body as static HTML; classes are themed in style.css (.guide-*).
const GUIDE_HTML = `
  <p class="guide-intro">
    rmscript lets you tell the robot what to do, step by step. It reads almost like
    plain English — each line is one instruction, run in order from top to bottom.
    Blank lines are ignored, so use them to keep things tidy.
  </p>
  <p class="guide-intro">
    Case doesn't matter: <code>look left</code>, <code>Look Left</code>, and
    <code>LOOK LEFT</code> all do the same thing.
  </p>

  <div class="guide-section">
    <h4>Basic movements</h4>
    <p><strong><code>look</code></strong> rotates the head to look in a direction:</p>
    <pre>look left
look right
look up
look down</pre>

    <p><strong><code>body</code></strong> rotates the whole body (the head follows along):</p>
    <pre>body left
body right</pre>

    <p><strong><code>tilt</code></strong> tilts the head sideways, like when you're curious:</p>
    <pre>tilt left
tilt right</pre>

    <p><strong><code>head</code></strong> moves the head in space without rotating it:</p>
    <pre>head up
head down
head left
head right
head forward
head backward</pre>

    <p>Each of these can return to the neutral position:</p>
    <pre>look center
body center
tilt center</pre>
    <p class="guide-note">You can also use <code>straight</code> or <code>neutral</code> instead of <code>center</code>.</p>

    <p><strong><code>reset</code></strong> sends everything (head, body and antennas) back to neutral at once:</p>
    <pre>reset</pre>
  </div>

  <div class="guide-section">
    <h4>Intensity and duration</h4>
    <p>Every movement has a default size and speed, so <code>look left</code> just works. To take control:</p>

    <p><strong>Intensity</strong> is how far it moves — degrees for rotations, millimeters for translations:</p>
    <pre>look left 45
head up 25</pre>

    <p><strong>Duration</strong> is how long it takes, in seconds. Add an <code>s</code> after the number:</p>
    <pre>look left 45 3.5s</pre>

    <p>You can also give just a duration (a default intensity is used):</p>
    <pre>look up 2s</pre>
  </div>

  <div class="guide-section">
    <h4>Words instead of numbers</h4>
    <p>If you prefer not to use numbers, use descriptive words instead.</p>
    <p><strong>For intensity:</strong> <code>tiny</code> <code>small</code> <code>alittle</code> <code>medium</code> <code>big</code> <code>alot</code> <code>maximum</code></p>
    <p><strong>For speed:</strong> <code>superslow</code> <code>slow</code> <code>fast</code> <code>superfast</code> <code>veryfast</code></p>
    <p>Use one, both, or neither:</p>
    <pre>body left superfast
body right maximum 1.5s
look up big and slow</pre>
  </div>

  <div class="guide-section">
    <h4>Combining movements</h4>
    <p>Use <code>and</code> to combine directions in one command:</p>
    <pre>look up and left
look down maximum and left alittle</pre>
    <p>You can also combine <em>different</em> commands so they happen together:</p>
    <pre>head up and look right
head up and look right and tilt left</pre>
    <p class="guide-note">This creates smooth, expressive movements where everything happens at once.</p>
  </div>

  <div class="guide-section">
    <h4>Antennas</h4>
    <p>The robot has two antennas, controllable together or separately.</p>
    <p><strong>Both together:</strong></p>
    <pre>antenna both up
antenna both down</pre>
    <p><strong>Each independently:</strong></p>
    <pre>antenna left up
antenna right down</pre>
    <p><strong>Combined:</strong></p>
    <pre>antenna left up and antenna right down</pre>
    <p>Directions are <code>up</code>, <code>down</code>, <code>left</code>, or <code>right</code>; or use clock positions (12 is up, 3 is to the side, 6 is down):</p>
    <pre>antenna left 2 and antenna right 10</pre>
  </div>

  <div class="guide-section">
    <h4>Pausing and repeating</h4>
    <p><strong><code>wait</code></strong> pauses the robot. Don't forget the <code>s</code>!</p>
    <pre>wait 1s
wait 0.5s</pre>
    <p><strong><code>repeat</code></strong> runs a sequence several times. The commands to repeat must be <strong>indented</strong>:</p>
    <pre>repeat 3
    tilt left maximum fast
    tilt right maximum fast
tilt center</pre>
    <p class="guide-note">The last line isn't indented, so it runs once, after the repetitions.</p>
    <p>Repeats can nest:</p>
    <pre>repeat 2
    antenna up
    repeat 3
        look left
        look right
    antenna down</pre>
  </div>

  <div class="guide-section">
    <h4>Pictures and sounds</h4>
    <p><strong><code>picture</code></strong> takes a photo of what the robot sees and hands it back to the AI — useful for behaviors that look at something and report on it:</p>
    <pre>look down
picture</pre>
    <p><strong><code>play</code></strong> plays a sound by name, from your sound library or the robot's built-in sounds (manage these from the 🔊 Sounds button):</p>
    <pre>play wake_up
antenna both up</pre>
    <p>By default the script keeps going while the sound plays. Add <code>pause</code> to wait for the sound to finish first:</p>
    <pre>play cheer pause
look up</pre>
  </div>

  <div class="guide-section">
    <h4>Comments</h4>
    <p>Lines starting with <code>#</code> are ignored. Use them for notes:</p>
    <pre># Wave hello
antenna both up
wait 0.5s
antenna both down</pre>
  </div>

  <div class="guide-section guide-warning">
    <h4>Watch out!</h4>
    <p><strong>Don't forget the <code>s</code> after durations:</strong></p>
    <pre>wait 2s      &#10003;
wait 2       &#10007; (won't work!)</pre>
    <p><strong>Always indent after <code>repeat</code>:</strong></p>
    <pre>repeat 3
    look left    &#10003; (indented)

repeat 3
look left        &#10007; (not indented — error!)</pre>
    <p><strong>You can't combine <code>wait</code> with movements using <code>and</code>:</strong></p>
    <pre>look left and wait 1s    &#10007; (doesn't work)

look left                &#10003; (use separate lines)
wait 1s</pre>
  </div>

  <div class="guide-section">
    <h4>Quick reference</h4>
    <table class="guide-table">
      <tr><th>Command</th><th>What it does</th><th>Example</th></tr>
      <tr><td><code>look</code></td><td>Rotate head to look somewhere</td><td><code>look left 45</code></td></tr>
      <tr><td><code>body</code></td><td>Rotate whole body</td><td><code>body right</code></td></tr>
      <tr><td><code>tilt</code></td><td>Tilt head sideways</td><td><code>tilt left</code></td></tr>
      <tr><td><code>head</code></td><td>Move head in space</td><td><code>head forward 10</code></td></tr>
      <tr><td><code>antenna</code></td><td>Move antennas</td><td><code>antenna both up</code></td></tr>
      <tr><td><code>reset</code></td><td>Everything back to neutral</td><td><code>reset</code></td></tr>
      <tr><td><code>wait</code></td><td>Pause</td><td><code>wait 1.5s</code></td></tr>
      <tr><td><code>repeat</code></td><td>Repeat a sequence</td><td><code>repeat 3</code></td></tr>
      <tr><td><code>picture</code></td><td>Capture a photo for the AI</td><td><code>picture</code></td></tr>
      <tr><td><code>play</code></td><td>Play a sound (add <code>pause</code> to wait)</td><td><code>play cheer</code></td></tr>
      <tr><td><code>#</code></td><td>Comment (ignored)</td><td><code># a note</code></td></tr>
    </table>
  </div>
`;

/** Open the script reference modal. Resolves when it closes. */
export function openScriptManual() {
  return new Promise((resolve) => {
    const overlay = h("div", { class: "modal-overlay", role: "presentation" });
    const dialog = h(
      "div",
      {
        class: "modal modal--manual",
        role: "dialog",
        "aria-modal": "true",
        "aria-labelledby": "script-manual-title",
      },
      h(
        "header",
        { class: "modal__header modal__header--bar" },
        h("h2", { id: "script-manual-title", class: "modal__title" }, "rmscript reference"),
        h("button", {
          type: "button",
          class: "modal__close",
          "aria-label": "Close",
          "data-action": "close",
          html: "&times;",
        })
      ),
      h("div", { class: "guide-body", html: GUIDE_HTML })
    );
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    function close() {
      window.removeEventListener("keydown", onKeydown);
      overlay.remove();
      resolve();
    }
    function onKeydown(event) {
      if (event.key === "Escape") close();
    }

    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) close();
    });
    dialog.querySelector("[data-action='close']").addEventListener("click", close);
    window.addEventListener("keydown", onKeydown);
    requestAnimationFrame(() => dialog.querySelector("[data-action='close']")?.focus());
  });
}
