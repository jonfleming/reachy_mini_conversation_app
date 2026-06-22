// CodeMirror 6 editor for rmscript, ported from the Reachy Mini Coding Lab.
// Imports the vendored, offline CodeMirror bundle (no CDN).
import {
  EditorView,
  basicSetup,
  EditorState,
  StateEffect,
  StateField,
  Decoration,
  HighlightStyle,
  syntaxHighlighting,
  StreamLanguage,
  tags,
} from "../../vendor/codemirror.js";

// --- Error line decoration (a red-highlighted line driven by compile errors) ---
const setErrorLine = StateEffect.define();
const clearErrorLineEffect = StateEffect.define();
const errorLineMark = Decoration.line({ class: "cm-errorLine" });

const errorLineField = StateField.define({
  create() {
    return Decoration.none;
  },
  update(decorations, tr) {
    for (const e of tr.effects) {
      if (e.is(clearErrorLineEffect)) return Decoration.none;
      if (e.is(setErrorLine)) {
        const lineNum = e.value;
        if (lineNum >= 1 && lineNum <= tr.state.doc.lines) {
          const line = tr.state.doc.line(lineNum);
          return Decoration.set([errorLineMark.range(line.from)]);
        }
      }
    }
    return decorations.map(tr.changes);
  },
  provide: (f) => EditorView.decorations.from(f),
});

// --- rmscript syntax: a context-aware stream tokenizer ---
const rmscriptLanguage = StreamLanguage.define({
  startState() {
    return { context: null };
  },
  token(stream, state) {
    if (stream.eatSpace()) return null;

    // Comments
    if (stream.match(/#.*/)) {
      state.context = null;
      return "comment";
    }
    // Duration with 's' suffix (e.g. 2s, 0.5s)
    if (stream.match(/\d+(?:\.\d+)?s\b/)) {
      state.context = null;
      return "number";
    }
    // Numbers (meaning depends on the preceding keyword)
    if (stream.match(/\d+(?:\.\d+)?/)) {
      if (state.context === "repeat") {
        state.context = null;
        return "meta";
      }
      if (state.context === "action") {
        state.context = null;
        return "propertyName";
      }
      state.context = null;
      return "number";
    }
    // Keywords and identifiers
    if (stream.match(/[a-zA-Z_][a-zA-Z0-9_]*/)) {
      const word = stream.current().toLowerCase();
      if (/^(look|tilt|body|head|antenna)$/.test(word)) {
        state.context = "action";
        return "keyword";
      }
      if (/^(reset)$/.test(word)) {
        state.context = null;
        return "keyword";
      }
      if (/^(repeat)$/.test(word)) {
        state.context = "repeat";
        return "meta";
      }
      if (/^(and|wait|turn)$/.test(word)) {
        state.context = word === "turn" ? "action" : null;
        return "meta";
      }
      if (/^(left|right|up|down|both|center|neutral|straight|backward|backwards|forward|back)$/.test(word)) {
        return "string";
      }
      if (/^(slow|fast|superslow|superfast)$/.test(word)) {
        state.context = null;
        return "number";
      }
      if (/^(alittle|tiny|small|medium|large|maximum|minimum|alot)$/.test(word)) {
        state.context = null;
        return "propertyName";
      }
      state.context = null;
      return "variableName";
    }
    stream.next();
    state.context = null;
    return null;
  },
});

const rmscriptHighlightStyle = HighlightStyle.define([
  { tag: tags.keyword, color: "#11733b", fontWeight: "bold" }, // green: actions
  { tag: tags.string, color: "#94b31f" }, // orange: directions
  { tag: tags.meta, color: "#9c27b0", fontWeight: "bold" }, // purple: control flow
  { tag: tags.number, color: "#4daaff" }, // blue: durations
  { tag: tags.propertyName, color: "#f38236" }, // brown: quantities
  { tag: tags.comment, color: "#888888", fontStyle: "italic" }, // gray
  { tag: tags.variableName, color: "#333333" }, // dark gray
]);

// Editor keeps a light surface (independent of the app theme) so the tuned
// highlight colors stay legible.
const editorTheme = EditorView.theme({
  ".cm-errorLine": { backgroundColor: "rgba(220, 53, 69, 0.15)" },
  "&": { height: "420px", fontSize: "15px" },
  "&.cm-editor": {
    border: "1px solid #d0d0d8",
    borderRadius: "10px",
    backgroundColor: "#fafafa",
  },
  "&.cm-editor.cm-focused": { borderColor: "#667eea", backgroundColor: "#fff", outline: "none" },
  ".cm-scroller": { fontFamily: "'Monaco', 'Menlo', 'Consolas', monospace", lineHeight: "1.6", overflow: "auto" },
  ".cm-content": { padding: "10px 0" },
  ".cm-gutters": { backgroundColor: "#f0f0f3", borderRight: "1px solid #e0e0e0", color: "#999" },
  ".cm-activeLineGutter": { backgroundColor: "#e6e6ea" },
  ".cm-activeLine": { backgroundColor: "#eeeef2" },
});

/** Create an rmscript editor in `parent`; `onChange(text)` fires on every edit. */
export function createRmscriptEditor(parent, initialContent, { onChange } = {}) {
  const state = EditorState.create({
    doc: initialContent || "",
    extensions: [
      basicSetup,
      rmscriptLanguage,
      syntaxHighlighting(rmscriptHighlightStyle),
      errorLineField,
      EditorView.updateListener.of((u) => {
        if (u.docChanged && onChange) onChange(u.state.doc.toString());
      }),
      editorTheme,
    ],
  });
  return new EditorView({ state, parent });
}

export const getContent = (view) => view.state.doc.toString();

export function setContent(view, text) {
  view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text || "" } });
}

export function showErrorLine(view, lineNum) {
  view.dispatch({ effects: setErrorLine.of(lineNum) });
}

export function clearError(view) {
  view.dispatch({ effects: clearErrorLineEffect.of(null) });
}
