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

const NEW_TEMPLATE = '"Describe what this behavior does (the AI reads this)"\n\nlook left\nwait 1s\nlook right\n';

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
    let source = NEW_TEMPLATE;
    if (name) {
      try {
        source = (await loadBehavior(name)).source || "";
      } catch (error) {
        showNotice(`Failed to load: ${describeError(error)}`);
        return;
      }
      if (signal.aborted) return;
    }

    const nameInput = h("input", {
      class: "settings-input",
      type: "text",
      placeholder: "behavior_name",
      value: name || "",
    });
    if (name) nameInput.disabled = true;
    const status = h("p", { class: "behaviors-verify", role: "status", "aria-live": "polite" });
    const editorMount = h("div", {});
    const saveBtn = h("button", { class: "btn btn--primary" }, "Save");
    const previewBtn = h("button", { class: "btn btn--ghost" }, "Preview on robot");
    const stopBtn = h("button", { class: "btn btn--ghost", disabled: true }, "Stop");
    let valid = false;

    function scheduleVerify(src) {
      if (verifyTimer) clearTimeout(verifyTimer);
      verifyTimer = setTimeout(() => runVerify(src), 400);
    }

    async function runVerify(src) {
      let res;
      try {
        res = await verifyRmscript(src);
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
        status.textContent = res.description ? `✓ Valid — ${res.description}` : "✓ Valid";
      } else {
        status.classList.add("is-error");
        const err = res.errors && res.errors[0];
        status.textContent = err ? `Line ${err.line ?? "?"}: ${err.message}` : "Invalid script.";
        if (err && err.line) showErrorLine(editor, err.line);
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

    editor = createRmscriptEditor(editorMount, source, { onChange: scheduleVerify });
    runVerify(source);

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
        res = await previewBehavior(getContent(editor));
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
        await saveBehavior(finalName, getContent(editor));
      } catch (error) {
        status.classList.add("is-error");
        const errs = error?.body?.errors;
        status.textContent = errs?.length
          ? `Line ${errs[0].line ?? "?"}: ${errs[0].message}`
          : `Failed to save: ${describeError(error)}`;
        return;
      }
      destroyEditor();
      await refreshList();
    });
  }

  await refreshList();
}
