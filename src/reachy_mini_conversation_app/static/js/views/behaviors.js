/** Robot Behaviors view: manage the shared library of rmscript-defined tools. */

import {
  listBehaviors,
  loadBehavior,
  saveBehavior,
  deleteBehavior,
  verifyRmscript,
  previewBehavior,
  abortBehavior,
  describeError,
  untilReady,
} from "../api.js";
import { h } from "../ui.js";
import {
  createRmscriptEditor,
  getContent,
  showErrorLine,
  clearError,
} from "../components/rmscript-editor.js";
import { openScriptManual } from "../components/script-manual.js";
import { openSoundLibrary } from "../components/sound-library.js";
import { confirmDialog } from "../components/confirm-dialog.js";

const NEW_DESCRIPTION = "Describe what this behavior does (the AI reads this)";
const NEW_BODY = "look left\nwait 1s\nlook right\n";

// An rmscript file starts with a quoted description, then the movement body. The
// editor edits the body alone while the description lives in its own field; these
// helpers split a saved file apart and recompose it. The composed prefix is always
// two lines (description + blank), so compiler error lines map to body line N - 2.
const PREFIX_LINES = 2;

function splitSource(source) {
  const m = source.match(/^\s*"([^"\n]*)"/);
  if (!m) return { description: "", body: source };
  return { description: m[1], body: source.slice(m[0].length).replace(/^[ \t]*(\r?\n)+/, "") };
}

function composeSource(description, body) {
  const desc = (description || "").replace(/"/g, "").trim();
  return `"${desc}"\n\n${body}`;
}

export async function mountBehaviorsView({ outlet, signal }) {
  const listEl = h("div", { class: "behaviors-list" }, h("p", { class: "muted" }, "Loading…"));
  const editorHost = h("div", { class: "behaviors-editor", hidden: true });
  const noticeEl = h("p", { class: "behaviors-notice", role: "status", "aria-live": "polite", hidden: true });

  // Inline replacement for window.alert (suppressed in the embedded app host).
  function showNotice(message, isError = true) {
    noticeEl.textContent = message;
    noticeEl.classList.toggle("is-error", isError);
    noticeEl.hidden = false;
  }

  const view = h(
    "section",
    { class: "view view--behaviors" },
    h(
      "header",
      { class: "view-header" },
      h("h1", { class: "view-title" }, "Robot Behaviors"),
      h("p", { class: "view-subtitle" }, "rmscript movements your personalities can call as tools.")
    ),
    h(
      "div",
      { class: "behaviors-toolbar" },
      h("button", { class: "btn btn--primary", onClick: () => openEditor(null) }, "New behavior"),
      h("button", { class: "btn btn--ghost", onClick: () => openSoundLibrary() }, "🔊 Sounds"),
      h("button", { class: "btn btn--ghost", onClick: () => openScriptManual() }, "📖 Script reference")
    ),
    noticeEl,
    listEl,
    editorHost
  );
  outlet.replaceChildren(view);

  let editor = null;
  let verifyTimer = null;
  let previewTimer = null;
  let previewing = false;

  function destroyEditor() {
    if (verifyTimer) {
      clearTimeout(verifyTimer);
      verifyTimer = null;
    }
    if (previewTimer) {
      clearTimeout(previewTimer);
      previewTimer = null;
    }
    if (previewing) {
      previewing = false;
      abortBehavior().catch(() => {}); // stop the robot if we leave mid-preview
    }
    if (editor) {
      editor.destroy();
      editor = null;
    }
    editorHost.replaceChildren();
    editorHost.hidden = true;
  }

  signal.addEventListener("abort", destroyEditor);

  function renderList(tools) {
    if (!tools.length) {
      listEl.replaceChildren(h("p", { class: "muted" }, "No behaviors yet. Create one to get started."));
      return;
    }
    listEl.replaceChildren(
      ...tools.map((t) =>
        h(
          "div",
          { class: "behavior-card" },
          h(
            "div",
            { class: "behavior-card__body" },
            h("span", { class: "behavior-card__name" }, t.name),
            h("span", { class: "behavior-card__desc" }, t.description || "—")
          ),
          h(
            "div",
            { class: "behavior-card__actions" },
            h("button", { class: "btn btn--ghost", onClick: () => openEditor(t.name) }, "Edit"),
            h("button", { class: "btn btn--ghost", onClick: () => removeBehavior(t.name) }, "Delete")
          )
        )
      )
    );
  }

  async function refreshList() {
    try {
      const data = await untilReady(listBehaviors, signal);
      if (signal.aborted) return;
      renderList(data.tools || []);
    } catch {
      if (!signal.aborted) listEl.replaceChildren(h("p", { class: "muted" }, "Couldn't load behaviors."));
    }
  }

  async function removeBehavior(name) {
    const ok = await confirmDialog({
      title: "Delete behavior?",
      message: `"${name}" will be permanently removed.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteBehavior(name);
    } catch (error) {
      showNotice(`Failed to delete: ${describeError(error)}`);
      return;
    }
    noticeEl.hidden = true;
    await refreshList();
  }

  async function openEditor(name) {
    destroyEditor();
    let description = NEW_DESCRIPTION;
    let body = NEW_BODY;
    if (name) {
      let source;
      try {
        source = (await loadBehavior(name)).source || "";
      } catch (error) {
        showNotice(`Failed to load: ${describeError(error)}`);
        return;
      }
      if (signal.aborted) return;
      ({ description, body } = splitSource(source));
    }

    const nameInput = h("input", {
      class: "settings-input",
      type: "text",
      placeholder: "behavior_name",
      value: name || "",
    });
    if (name) nameInput.disabled = true;
    const descInput = h("input", {
      class: "settings-input",
      type: "text",
      placeholder: "What this behavior does (the AI reads this)",
      value: description,
    });
    const status = h("p", { class: "behaviors-verify", role: "status", "aria-live": "polite" });
    const editorMount = h("div", {});
    const saveBtn = h("button", { class: "btn btn--primary" }, "Save");
    const previewBtn = h("button", { class: "btn btn--ghost" }, "Preview on robot");
    const stopBtn = h("button", { class: "btn btn--ghost", disabled: true }, "Stop");
    let valid = false;

    const currentSource = () => composeSource(descInput.value, getContent(editor));

    function scheduleVerify() {
      if (verifyTimer) clearTimeout(verifyTimer);
      verifyTimer = setTimeout(runVerify, 400);
    }

    async function runVerify() {
      let res;
      try {
        res = await verifyRmscript(currentSource());
      } catch {
        return;
      }
      if (signal.aborted || !editor) return;
      clearError(editor);
      valid = !!res.success;
      saveBtn.disabled = !valid;
      previewBtn.disabled = !valid || previewing;
      if (res.success) {
        status.classList.remove("is-error");
        status.textContent = "✓ Valid";
      } else {
        status.classList.add("is-error");
        const err = res.errors && res.errors[0];
        // Compiler lines count the description prefix; the editor shows the body alone.
        const bodyLine = err && err.line ? Math.max(1, err.line - PREFIX_LINES) : null;
        status.textContent = err ? `Line ${bodyLine ?? "?"}: ${err.message}` : "Invalid script.";
        if (bodyLine) showErrorLine(editor, bodyLine);
      }
    }

    const panel = h(
      "div",
      { class: "behaviors-editor__panel" },
      h(
        "label",
        { class: "settings-field" },
        h("span", { class: "settings-label" }, "Name"),
        nameInput
      ),
      h(
        "label",
        { class: "settings-field" },
        h("span", { class: "settings-label" }, "Description"),
        descInput
      ),
      editorMount,
      status,
      h(
        "div",
        { class: "settings-actions" },
        saveBtn,
        previewBtn,
        stopBtn,
        h("button", { class: "btn btn--ghost", onClick: destroyEditor }, "Cancel")
      )
    );
    editorHost.replaceChildren(panel);
    editorHost.hidden = false;

    editor = createRmscriptEditor(editorMount, body, { onChange: scheduleVerify });
    descInput.addEventListener("input", scheduleVerify);
    runVerify();

    // Reset the buttons to idle; pass a status message, or null to leave it as-is.
    function endPreview(message) {
      if (previewTimer) {
        clearTimeout(previewTimer);
        previewTimer = null;
      }
      previewing = false;
      stopBtn.disabled = true;
      previewBtn.disabled = !valid;
      if (message !== null) {
        status.classList.remove("is-error");
        status.textContent = message;
      }
    }

    previewBtn.addEventListener("click", async () => {
      previewing = true;
      previewBtn.disabled = true;
      stopBtn.disabled = false;
      status.classList.remove("is-error");
      status.textContent = "Playing on robot…";
      let res;
      try {
        res = await previewBehavior(currentSource());
      } catch (error) {
        endPreview(null);
        status.classList.add("is-error");
        status.textContent = `Preview failed: ${describeError(error)}`;
        return;
      }
      if (signal.aborted || !editor) return;
      // The moves are queued; flip back to idle when the motion finishes on its own.
      previewTimer = setTimeout(() => endPreview("Done."), Math.ceil((res?.duration || 0) * 1000));
    });

    stopBtn.addEventListener("click", () => {
      endPreview("Stopped.");
      abortBehavior().catch(() => {});
    });

    saveBtn.addEventListener("click", async () => {
      const finalName = (nameInput.value || "").trim();
      if (!finalName) {
        status.classList.add("is-error");
        status.textContent = "Enter a name.";
        return;
      }
      try {
        await saveBehavior(finalName, currentSource());
      } catch (error) {
        status.classList.add("is-error");
        const errs = error?.body?.errors;
        status.textContent = errs?.length
          ? `Line ${Math.max(1, (errs[0].line ?? PREFIX_LINES + 1) - PREFIX_LINES)}: ${errs[0].message}`
          : `Failed to save: ${describeError(error)}`;
        return;
      }
      destroyEditor();
      await refreshList();
    });
  }

  await refreshList();
}
