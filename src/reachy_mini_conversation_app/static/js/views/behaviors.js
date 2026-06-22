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

const NEW_TEMPLATE = '"Describe what this behavior does (the AI reads this)"\n\nlook left\nwait 1s\nlook right\n';

export async function mountBehaviorsView({ outlet, signal }) {
  const listEl = h("div", { class: "behaviors-list" }, h("p", { class: "muted" }, "Loading…"));
  const editorHost = h("div", { class: "behaviors-editor", hidden: true });

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
      h("button", { class: "btn btn--primary", onClick: () => openEditor(null) }, "New behavior")
    ),
    listEl,
    editorHost
  );
  outlet.replaceChildren(view);

  let editor = null;
  let verifyTimer = null;
  let previewing = false;

  function destroyEditor() {
    if (verifyTimer) {
      clearTimeout(verifyTimer);
      verifyTimer = null;
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
    if (!window.confirm(`Delete behavior "${name}"?`)) return;
    try {
      await deleteBehavior(name);
    } catch (error) {
      window.alert(`Failed to delete: ${describeError(error)}`);
      return;
    }
    await refreshList();
  }

  async function openEditor(name) {
    destroyEditor();
    let source = NEW_TEMPLATE;
    if (name) {
      try {
        source = (await loadBehavior(name)).source || "";
      } catch (error) {
        window.alert(`Failed to load: ${describeError(error)}`);
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

    previewBtn.addEventListener("click", async () => {
      previewing = true;
      previewBtn.disabled = true;
      stopBtn.disabled = false;
      status.classList.remove("is-error");
      status.textContent = "Playing on robot…";
      try {
        const res = await previewBehavior(getContent(editor));
        if (res?.ok === false) {
          status.classList.add("is-error");
          status.textContent = "Preview failed (script did not run).";
        } else {
          status.textContent = res?.aborted ? "Stopped." : "Done.";
        }
      } catch (error) {
        status.classList.add("is-error");
        status.textContent =
          error?.body?.error === "loop_unavailable" || error?.body?.error === "preview_unavailable"
            ? "Robot not available for preview."
            : `Preview failed: ${describeError(error)}`;
      } finally {
        previewing = false;
        stopBtn.disabled = true;
        previewBtn.disabled = !valid;
      }
    });

    stopBtn.addEventListener("click", () => {
      stopBtn.disabled = true;
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
