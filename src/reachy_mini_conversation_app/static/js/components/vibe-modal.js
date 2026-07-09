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
