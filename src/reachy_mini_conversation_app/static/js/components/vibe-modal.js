/** Modals for the vibe-create flow: a description prompt, then a light review. */

import { h } from "../ui.js";

const NAME_PATTERN = /^[a-zA-Z0-9_-]+$/;

/** Shared modal scaffolding: overlay + focus trap + Escape/click-out/abort handling. */
function mountModal({ dialog, signal, resolve, focusSelector }) {
  const overlay = h("div", { class: "modal-overlay", role: "presentation" });
  overlay.appendChild(dialog);
  document.body.appendChild(overlay);
  requestAnimationFrame(() => dialog.querySelector(focusSelector)?.focus());

  function close(value) {
    window.removeEventListener("keydown", onKeydown);
    signal?.removeEventListener("abort", onAbort);
    overlay.remove();
    resolve(value);
  }
  function onKeydown(event) {
    if (event.key === "Escape") close(null);
  }
  function onAbort() {
    close(null);
  }
  overlay.addEventListener("click", (event) => {
    if (event.target === overlay) close(null);
  });
  window.addEventListener("keydown", onKeydown);
  signal?.addEventListener("abort", onAbort);
  dialog.querySelector("[data-action='cancel']")?.addEventListener("click", () => close(null));
  return close;
}

function showError(errorBox, message) {
  errorBox.textContent = message;
  errorBox.classList.add("is-visible");
}

// The bar aims to reach 100% over roughly this long, matching typical generation latency.
const PROGRESS_TARGET_MS = 80000;

/**
 * Show a non-dismissable "generating" modal with a jagged progress bar that
 * creeps toward 100% over ~80s. Returns a controller:
 *   - finish(): fill to 100% smoothly, then remove the modal (await it).
 *   - close():  remove the modal immediately (on error/abort).
 *
 * The bar caps just short of 100% until finish() is called, so it never claims
 * completion before the real draft has arrived — even if generation runs long.
 */
export function openVibeProgressModal({ signal } = {}) {
  const fill = h("div", { class: "vibe-progress__fill" });
  const label = h("span", { class: "vibe-progress__pct" }, "0%");
  const track = h(
    "div",
    { class: "vibe-progress__track", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": "0" },
    fill
  );
  const dialog = h(
    "div",
    { class: "modal modal--progress", role: "dialog", "aria-modal": "true", "aria-labelledby": "vibe-progress-title" },
    h(
      "header",
      { class: "modal__header" },
      h("h2", { id: "vibe-progress-title", class: "modal__title" }, "Creating your personality…"),
      h("p", { class: "modal__subtitle" }, "Reachy is dreaming up a character and inventing its moves.")
    ),
    h("div", { class: "vibe-progress" }, track, label)
  );
  const overlay = h("div", { class: "modal-overlay", role: "presentation" });
  overlay.appendChild(dialog);
  document.body.appendChild(overlay);

  let percent = 0;
  let timer = null;

  function render() {
    const shown = Math.min(100, Math.round(percent));
    fill.style.width = `${shown}%`;
    label.textContent = `${shown}%`;
    track.setAttribute("aria-valuenow", String(shown));
  }

  // Self-scheduling tick with a randomized cadence and jittered step, so the
  // bar advances in visibly uneven jerks rather than a smooth glide.
  function tick() {
    const dt = 240 + Math.random() * 420; // 0.24–0.66s between updates
    const base = (dt / PROGRESS_TARGET_MS) * 100; // even-pace share for this slice
    // ~15% of ticks nearly stall; the rest run 0.4×–2.2× the even pace.
    const jitter = Math.random() < 0.15 ? Math.random() * 0.25 : 0.4 + Math.random() * 1.8;
    percent = Math.min(percent + base * jitter, 95);
    render();
    timer = setTimeout(tick, dt);
  }

  function stop() {
    if (timer) clearTimeout(timer);
    timer = null;
  }
  function close() {
    stop();
    signal?.removeEventListener("abort", close);
    overlay.remove();
  }
  signal?.addEventListener("abort", close);
  timer = setTimeout(tick, 180);

  return {
    close,
    /** Run the bar to 100%, hold briefly so it reads as done, then remove the modal. */
    finish() {
      stop();
      return new Promise((resolve) => {
        percent = 100;
        render();
        setTimeout(() => {
          close();
          resolve();
        }, 450);
      });
    },
  };
}

/** Ask the user to describe the personality. Resolves to the text, or null if cancelled. */
export function openVibeInputModal({ signal } = {}) {
  return new Promise((resolve) => {
    const dialog = h(
      "div",
      { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "vibe-title" },
      h(
        "header",
        { class: "modal__header" },
        h("h2", { id: "vibe-title", class: "modal__title" }, "Vibe-create a personality"),
        h(
          "p",
          { class: "modal__subtitle" },
          "Describe the character you want in a sentence or two. Reachy writes the prompt and invents its own moves."
        )
      ),
      h(
        "form",
        { class: "modal__form" },
        h(
          "label",
          { class: "modal__field" },
          h("span", { class: "modal__label" }, "Describe your personality"),
          h("textarea", {
            name: "description",
            required: "required",
            rows: "5",
            placeholder:
              "e.g. A grumpy old pirate who suspiciously looks around and grumbles about landlubbers.",
            class: "modal__textarea",
          })
        ),
        h("p", { class: "modal__error", role: "alert", "aria-live": "polite" }),
        h(
          "div",
          { class: "modal__actions" },
          h("button", { type: "button", class: "btn btn--ghost", "data-action": "cancel" }, "Cancel"),
          h("button", { type: "submit", class: "btn btn--primary" }, "Generate")
        )
      )
    );

    const close = mountModal({ dialog, signal, resolve, focusSelector: "textarea" });
    const errorBox = dialog.querySelector(".modal__error");
    dialog.querySelector("textarea").addEventListener("input", () => errorBox.classList.remove("is-visible"));
    dialog.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      const description = String(new FormData(event.target).get("description") || "").trim();
      if (!description) return showError(errorBox, "Please describe the personality.");
      close(description);
    });
  });
}

/**
 * Review a generated draft before saving. Prefilled and editable, but designed so a
 * beginner can accept in one click. Resolves to the edited draft, or null if cancelled.
 *
 * @param {{ draft: object, availableTools?: string[], signal?: AbortSignal }} options
 */
export function openVibeReviewModal({ draft, availableTools = [], signal } = {}) {
  const behaviors = (draft.new_behaviors || []).filter((b) => b.compiled_ok);
  const behaviorNames = new Set(behaviors.map((b) => b.name));
  // The tool checklist offers existing tools only; the new behaviors are shown separately
  // and always created + enabled. Pre-check whatever the model chose to enable.
  const enabledSet = new Set(draft.enable_tools || []);
  const toolChoices = [...new Set(availableTools)].filter((t) => !behaviorNames.has(t)).sort();

  return new Promise((resolve) => {
    const dialog = h(
      "div",
      { class: "modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "vibe-review-title" },
      h(
        "header",
        { class: "modal__header" },
        h("h2", { id: "vibe-review-title", class: "modal__title" }, "Here's your personality"),
        h(
          "p",
          { class: "modal__subtitle" },
          "Looks good? Just hit Create & start. Or tweak anything below first."
        )
      ),
      h(
        "form",
        { class: "modal__form" },
        h(
          "label",
          { class: "modal__field" },
          h("span", { class: "modal__label" }, "Name"),
          h("input", {
            type: "text",
            name: "name",
            required: "required",
            autocomplete: "off",
            spellcheck: "false",
            pattern: "[a-zA-Z0-9_-]+",
            value: draft.name || "",
            class: "modal__input",
          })
        ),
        h(
          "label",
          { class: "modal__field" },
          h("span", { class: "modal__label" }, "Instructions"),
          h(
            "textarea",
            { name: "instructions", required: "required", rows: "8", class: "modal__textarea" },
            draft.instructions || ""
          )
        ),
        h(
          "label",
          { class: "modal__field" },
          h("span", { class: "modal__label" }, "Startup greeting prompt"),
          h("textarea", { name: "greeting", rows: "3", class: "modal__textarea" }, draft.greeting || "")
        ),
        buildBehaviorsField(behaviors),
        buildReviewToolsField(toolChoices, enabledSet),
        h("p", { class: "modal__error", role: "alert", "aria-live": "polite" }),
        h(
          "div",
          { class: "modal__actions" },
          h("button", { type: "button", class: "btn btn--ghost", "data-action": "cancel" }, "Cancel"),
          h("button", { type: "submit", class: "btn btn--primary" }, "Create & start")
        )
      )
    );

    const close = mountModal({ dialog, signal, resolve, focusSelector: ".btn--primary" });
    const errorBox = dialog.querySelector(".modal__error");
    dialog.querySelectorAll("input, textarea").forEach((field) => {
      field.addEventListener("input", () => errorBox.classList.remove("is-visible"));
    });
    dialog.querySelector("form").addEventListener("submit", (event) => {
      event.preventDefault();
      const formData = new FormData(event.target);
      const name = String(formData.get("name") || "").trim();
      const instructions = String(formData.get("instructions") || "").trim();
      const greeting = String(formData.get("greeting") || "").trim();
      if (!name) return showError(errorBox, "Please pick a name.");
      if (!NAME_PATTERN.test(name)) {
        return showError(errorBox, "Use only letters, numbers, dashes or underscores.");
      }
      if (!instructions) return showError(errorBox, "Please write some instructions.");
      const enable_tools = Array.from(dialog.querySelectorAll('input[name="tool"]:checked')).map((el) => el.value);
      // Carry the (validated) behaviors through untouched so commit can write them.
      close({ name, instructions, greeting, enable_tools, new_behaviors: behaviors });
    });
  });
}

/** Read-only list of the new moves the model wrote (only shown when there are any). */
function buildBehaviorsField(behaviors) {
  if (!behaviors.length) return null;
  return h(
    "fieldset",
    { class: "modal__field modal__behaviors" },
    h("legend", { class: "modal__label" }, "New moves Reachy will learn"),
    h(
      "ul",
      { class: "modal__behaviors-list" },
      ...behaviors.map((b) =>
        h(
          "li",
          { class: "modal__behavior" },
          h("span", { class: "modal__behavior-name" }, b.name),
          b.description ? h("span", { class: "modal__behavior-desc" }, b.description) : null
        )
      )
    )
  );
}

/** Existing-tools checklist, pre-checking whatever the model chose. */
function buildReviewToolsField(toolChoices, enabledSet) {
  if (!toolChoices.length) return null;
  return h(
    "fieldset",
    { class: "modal__field modal__tools" },
    h("legend", { class: "modal__label" }, "Tools"),
    h(
      "div",
      { class: "modal__tools-grid" },
      ...toolChoices.map((tool) =>
        h(
          "label",
          { class: "modal__tool" },
          h("input", {
            type: "checkbox",
            name: "tool",
            value: tool,
            checked: enabledSet.has(tool) ? "checked" : null,
          }),
          h("span", null, tool)
        )
      )
    )
  );
}
