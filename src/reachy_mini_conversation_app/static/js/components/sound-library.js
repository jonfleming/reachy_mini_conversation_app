/** Modal sound library: list user + built-in sounds, upload and remove user ones.
 * Sounds listed here are what `play <name>` can reference in a behavior. */

import { listSounds, uploadSound, deleteSound, describeError } from "../api.js";
import { h } from "../ui.js";
import { confirmDialog } from "./confirm-dialog.js";

/** Open the sound library modal. Resolves when it closes. */
export function openSoundLibrary() {
  return new Promise((resolve) => {
    const listHost = h("div", { class: "sound-library__lists" }, h("p", { class: "muted" }, "Loading…"));
    const status = h("p", { class: "sound-library__status", role: "status", "aria-live": "polite" });
    const fileInput = h("input", { type: "file", accept: ".wav,.mp3,.ogg,audio/*", hidden: true });
    const uploadBtn = h("button", { class: "btn btn--primary", onClick: () => fileInput.click() }, "Upload sound…");

    const overlay = h("div", { class: "modal-overlay", role: "presentation" });
    const dialog = h(
      "div",
      { class: "modal modal--manual", role: "dialog", "aria-modal": "true", "aria-labelledby": "sound-library-title" },
      h(
        "header",
        { class: "modal__header modal__header--bar" },
        h("h2", { id: "sound-library-title", class: "modal__title" }, "Sounds"),
        h("button", {
          type: "button",
          class: "modal__close",
          "aria-label": "Close",
          "data-action": "close",
          html: "&times;",
        })
      ),
      h(
        "div",
        { class: "sound-library__body" },
        h(
          "p",
          { class: "sound-library__hint" },
          "Trigger any of these from a behavior with “play <name>”. Upload your own, or use the robot's built-in sounds."
        ),
        listHost,
        status,
        h("div", { class: "sound-library__actions" }, uploadBtn, fileInput)
      )
    );
    overlay.appendChild(dialog);
    document.body.appendChild(overlay);

    function render(data) {
      const user = data?.user || [];
      const builtin = data?.builtin || [];
      const sections = [h("h3", { class: "sound-library__group" }, "Your sounds")];
      sections.push(
        user.length
          ? h(
              "ul",
              { class: "sound-list" },
              ...user.map((name) =>
                h(
                  "li",
                  { class: "sound-list__item" },
                  h("span", { class: "sound-list__name" }, name),
                  h("button", {
                    class: "sound-list__remove",
                    "aria-label": `Remove ${name}`,
                    title: "Remove",
                    onClick: () => removeSound(name),
                    html: "&times;",
                  })
                )
              )
            )
          : h("p", { class: "muted small" }, "No uploaded sounds yet.")
      );
      sections.push(h("h3", { class: "sound-library__group" }, "Built-in sounds"));
      sections.push(
        builtin.length
          ? h(
              "ul",
              { class: "sound-list" },
              ...builtin.map((name) =>
                h("li", { class: "sound-list__item is-readonly" }, h("span", { class: "sound-list__name" }, name))
              )
            )
          : h("p", { class: "muted small" }, "No built-in sounds found.")
      );
      listHost.replaceChildren(...sections);
    }

    async function refresh() {
      try {
        render(await listSounds());
      } catch (error) {
        listHost.replaceChildren(h("p", { class: "muted" }, `Couldn't load sounds: ${describeError(error)}`));
      }
    }

    async function removeSound(name) {
      const ok = await confirmDialog({
        title: "Remove sound?",
        message: `"${name}" will be deleted from your sound library.`,
        confirmLabel: "Remove",
        danger: true,
      });
      if (!ok) return;
      status.classList.remove("is-error");
      try {
        render(await deleteSound(name));
        status.textContent = `Removed "${name}".`;
      } catch (error) {
        status.classList.add("is-error");
        status.textContent = `Failed to remove: ${describeError(error)}`;
      }
    }

    fileInput.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      if (!file) return;
      status.classList.remove("is-error");
      status.textContent = `Uploading "${file.name}"…`;
      try {
        const data = await uploadSound(file);
        render(data);
        status.textContent = `Added "${data.name}".`;
      } catch (error) {
        status.classList.add("is-error");
        status.textContent = `Upload failed: ${describeError(error)}`;
      }
      fileInput.value = "";
    });

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

    refresh();
  });
}
