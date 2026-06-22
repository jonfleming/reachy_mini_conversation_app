# Vendored frontend dependencies

These files are committed so the UI works offline (the robot may run on a LAN
with no internet). Do not edit by hand — rebuild from source.

## codemirror.js

A single self-contained ESM bundle of the CodeMirror 6 symbols used by the
rmscript editor (`js/components/rmscript-editor.js`). Versions match the
Reachy Mini Coding Lab.

Rebuild:

```sh
mkdir cm-build && cd cm-build
npm install codemirror@6.0.1 @codemirror/state@6.4.1 @codemirror/view@6.26.3 \
            @codemirror/language@6.10.1 @lezer/highlight@1.2.0 esbuild
cat > entry.js <<'EOF'
export { EditorView, basicSetup } from "codemirror";
export { EditorState, Compartment, StateEffect, StateField } from "@codemirror/state";
export { Decoration } from "@codemirror/view";
export { HighlightStyle, syntaxHighlighting, StreamLanguage } from "@codemirror/language";
export { tags } from "@lezer/highlight";
EOF
# --alias dedupes @codemirror/state: npm nests extra copies under lint/search/
# commands, and multiple instances break CodeMirror's instanceof extension checks.
./node_modules/.bin/esbuild entry.js --bundle --format=esm --minify \
  --legal-comments=none \
  --alias:@codemirror/state="$PWD/node_modules/@codemirror/state" \
  --outfile=../codemirror.js
```
