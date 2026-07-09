"""Vibe-create a personality from a plain-language description.

Turns a one-line description ("a grumpy pirate that looks around suspiciously")
into a ready personality by calling a capable LLM (GLM-5.2 via HF Inference
Providers): a system prompt, a greeting, a set of existing tools to enable, and
new rmscript behaviors. New behaviors are compile-validated with a bounded
auto-repair loop, and every attempt is logged so we can monitor how often the
model gets rmscript wrong.

Pure logic — no FastAPI. Persists nothing; the caller commits the returned draft.
"""

from __future__ import annotations
import re
import ast
import json
import logging
from typing import Any, Dict, List, Callable
from pathlib import Path
from functools import lru_cache
from dataclasses import field, dataclass

from rmscript import compile_script

from . import sound_library
from .config import config
from .personality import DEFAULT_OPTION, _tools_dir, _sanitize_name, _write_profile, available_tools_for
from .rmscript_library import list_rmscript_tools, write_rmscript_tool


logger = logging.getLogger(__name__)

# How many times to ask the model to fix a behavior that fails to compile.
MAX_REPAIR_ATTEMPTS = 2
# Guardrail so a runaway response can't spam the shared tool library.
MAX_NEW_BEHAVIORS = 8
# Output-token ceiling. GLM-5.2 is a reasoning model whose (separate) thinking
# trace shares the generation budget, so this must be generous — too low and the
# JSON answer is truncated mid-object and fails to parse.
DEFAULT_MAX_TOKENS = 24000

# Default description compile_script assigns when a script omits its own.
_DEFAULT_SCRIPT_DESCRIPTION = "This is a Reachy Mini Script"

# A callable that takes a chat-messages list and returns the assistant text.
# Injectable so tests can run the whole pipeline without any network.
Complete = Callable[[List[Dict[str, str]]], str]


class VibeError(RuntimeError):
    """Raised when the viber cannot produce a usable draft."""


@dataclass
class NewBehavior:
    """One rmscript behavior invented by the viber (prefixed, validated)."""

    name: str
    description: str
    source: str
    compiled_ok: bool
    warnings: List[str] = field(default_factory=list)


@dataclass
class VibeDraft:
    """An in-memory personality proposal. Nothing on disk yet."""

    name: str
    instructions: str
    greeting: str
    enable_tools: List[str]
    new_behaviors: List[NewBehavior]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for the HTTP layer / front-end review modal."""
        return {
            "name": self.name,
            "instructions": self.instructions,
            "greeting": self.greeting,
            "enable_tools": list(self.enable_tools),
            "new_behaviors": [
                {
                    "name": b.name,
                    "description": b.description,
                    "source": b.source,
                    "compiled_ok": b.compiled_ok,
                    "warnings": list(b.warnings),
                }
                for b in self.new_behaviors
            ],
        }


# --------------------------------------------------------------------------- #
# Token availability
# --------------------------------------------------------------------------- #
def has_token() -> bool:
    """Whether an HF token is available (explicit env or a cached CLI login)."""
    if (config.HF_TOKEN or "").strip():
        return True
    try:
        from huggingface_hub import get_token

        return bool(get_token())
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Language reference + tool catalog (context fed to the model)
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def load_rmscript_reference() -> str:
    """Return the vendored rmscript language reference (cached)."""
    path = Path(__file__).parent / "rmscript_reference.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:  # pragma: no cover - packaging error
        logger.warning("rmscript reference doc missing at %s: %s", path, e)
        return ""


def _extract_tool_meta(py_path: Path) -> Dict[str, str] | None:
    """Statically read a Tool subclass's ``name``/``description`` from a .py file.

    Uses ``ast`` rather than importing, so heavy/optional tool dependencies are
    never triggered just to build the catalog.
    """
    try:
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(isinstance(b, ast.Name) and b.id == "Tool" for b in node.bases):
            continue
        meta: Dict[str, str] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
                if isinstance(stmt.value.value, str):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name) and target.id in {"name", "description"}:
                            meta[target.id] = stmt.value.value
        if "name" in meta:
            return {"name": meta["name"], "description": meta.get("description", "")}
    return None


def build_tool_catalog() -> List[Dict[str, str]]:
    """List ``{name, description}`` for every existing tool a personality may enable.

    Combines the shared Python tools (descriptions read statically) with the
    shared rmscript behaviors (descriptions from their compiled docstring).
    """
    catalog: Dict[str, str] = {}

    # rmscript behaviors (name + description come straight from the library).
    for tool in list_rmscript_tools():
        catalog[tool["name"]] = tool.get("description", "")

    # Shared Python tools: names via available_tools_for, descriptions via ast.
    rmscript_names = set(catalog)
    for name in available_tools_for(DEFAULT_OPTION):
        if name in rmscript_names or name in catalog:
            continue
        py_path = _tools_dir() / f"{name}.py"
        meta = _extract_tool_meta(py_path) if py_path.is_file() else None
        catalog[name] = (meta or {}).get("description", "") if meta else ""

    return [{"name": n, "description": catalog[n]} for n in sorted(catalog)]


def _available_sounds() -> List[str]:
    """Sound names usable in ``play``/``loop`` (user + built-in)."""
    try:
        return sorted(set(sound_library.list_user_sounds()) | set(sound_library.list_builtin_sounds()))
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Prompt construction
# --------------------------------------------------------------------------- #
_OUTPUT_SCHEMA = """
Return ONLY a single JSON object (no prose, no markdown fences) with this shape:
{
  "name": "short_snake_case_name",
  "instructions": "The system prompt: who the robot is, how it talks, when it uses its tools.",
  "greeting": "A short in-character opening line (optional, may be empty).",
  "enable_tools": ["exact_name_of_an_existing_tool", "..."],
  "new_behaviors": [
    {
      "name": "short_snake_case_behavior_name",
      "description": "One sentence describing what the movement does (the AI reads this).",
      "rmscript": "the rmscript source code for this behavior"
    }
  ]
}
""".strip()


def build_generation_messages(
    description: str,
    catalog: List[Dict[str, str]],
    sounds: List[str],
) -> List[Dict[str, str]]:
    """Build the chat messages for the main generation call."""
    reference = load_rmscript_reference()
    catalog_lines = "\n".join(f"- {t['name']}: {t['description']}".rstrip() for t in catalog) or "(none)"
    sounds_line = ", ".join(sounds) if sounds else "(none available)"

    system = f"""You design personalities for Reachy Mini, a small expressive desk robot with a \
moving head, two antennas, a rotating body, a camera and a speaker.

A personality has: a system prompt ("instructions"), an optional greeting, a set of existing \
tools it may use, and optionally NEW movement behaviors you write in the "rmscript" language.

Your job: from the user's description, produce a complete personality.

RULES
- New behaviors MUST be written in rmscript (never Python). Keep each one short.
- To use an existing capability, list its exact name in "enable_tools" — do NOT reinvent it as a behavior.
- Reference sounds only by a name from the available list; if none fit, omit sound commands.
- Names must be snake_case (letters, digits, underscores). Keep behaviors focused (a few lines).
- Behavior names should be short and describe the ACTION only (e.g. "perk_up", "look_around", \
"happy_wiggle"). Do NOT repeat the personality's name or theme in them — they are namespaced automatically.
- The first line of each behavior's rmscript should be its description as a quoted string.
- Write the instructions in the same language the user used in their description.

EXISTING TOOLS you may enable (by exact name):
{catalog_lines}

SOUNDS available to `play`/`loop`:
{sounds_line}

RMSCRIPT LANGUAGE REFERENCE
{reference}

{_OUTPUT_SCHEMA}"""

    user = f"Create a personality for this description:\n\n{description.strip()}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _build_repair_messages(source: str, errors: List[Any]) -> List[Dict[str, str]]:
    """Build messages asking the model to fix a non-compiling behavior."""
    reference = load_rmscript_reference()
    err_lines = "\n".join(
        f"- line {getattr(e, 'line', '?')}, column {getattr(e, 'column', '?')}: {getattr(e, 'message', e)}"
        for e in errors
    )
    system = (
        "You fix rmscript programs for the Reachy Mini robot. "
        "Return ONLY the corrected rmscript source — no explanations, no markdown fences.\n\n"
        "RMSCRIPT LANGUAGE REFERENCE\n" + reference
    )
    user = f"This rmscript fails to compile:\n\n{source}\n\nCompiler errors:\n{err_lines}\n\nReturn the corrected rmscript."
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #
def _strip_fences(text: str) -> str:
    """Remove a leading/trailing markdown code fence if present."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_-]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def parse_draft_json(text: str) -> Dict[str, Any]:
    """Parse the model's JSON reply, tolerating fences and surrounding prose."""
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise VibeError("The model did not return valid JSON.")


def _apply_renames(text: str, renames: Dict[str, str]) -> str:
    """Replace whole-word occurrences of each raw behavior name with its prefixed name.

    Longest names first, so a name that is a prefix of another isn't half-replaced.
    """
    if not text or not renames:
        return text
    for raw in sorted(renames, key=len, reverse=True):
        prefixed = renames[raw]
        text = re.sub(rf"\b{re.escape(raw)}\b", prefixed, text)
    return text


def _ensure_description_line(source: str, description: str) -> str:
    """Prepend a quoted description line if the script lacks its own."""
    result = compile_script(source)
    if (result.description or "").strip() and result.description != _DEFAULT_SCRIPT_DESCRIPTION:
        return source
    desc = (description or "").strip()
    if not desc:
        return source
    safe = desc.replace('"', "'")
    return f'"{safe}"\n{source.lstrip()}'


# --------------------------------------------------------------------------- #
# Validate + repair
# --------------------------------------------------------------------------- #
def _validate_and_repair(source: str, complete: Complete) -> tuple[str, Any, int]:
    """Compile ``source``; if it fails, ask the model to fix it (bounded).

    Returns ``(final_source, compile_result, repair_attempts)``. The last
    attempt is kept even if it still fails, so nothing is silently dropped.
    """
    current = source
    result = compile_script(current)
    attempts = 0
    while not result.success and attempts < MAX_REPAIR_ATTEMPTS:
        attempts += 1
        try:
            fixed = _strip_fences(complete(_build_repair_messages(current, result.errors)))
        except Exception as e:
            logger.warning("vibe repair call failed: %s", e)
            break
        if not fixed.strip():
            break
        current = fixed
        result = compile_script(current)
    return current, result, attempts


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _default_complete(messages: List[Dict[str, str]]) -> str:
    """Call GLM-5.2 (or the configured model) via HF Inference Providers."""
    from huggingface_hub import InferenceClient

    token = (config.HF_TOKEN or "").strip() or None
    client = InferenceClient(provider=config.VIBE_PROVIDER, api_key=token)
    resp = client.chat.completions.create(
        model=config.VIBE_MODEL,
        messages=messages,
        max_tokens=DEFAULT_MAX_TOKENS,
        temperature=0.7,
    )
    return resp.choices[0].message.content or ""


def generate_personality(description: str, *, complete: Complete | None = None) -> VibeDraft:
    """Generate (and validate/repair) a personality draft from a description.

    ``complete`` is injectable for testing; it defaults to the live GLM call.
    """
    if not (description or "").strip():
        raise VibeError("Please describe the personality you want.")
    complete = complete or _default_complete

    catalog = build_tool_catalog()
    catalog_names = {t["name"] for t in catalog}
    sounds = _available_sounds()

    try:
        raw = complete(build_generation_messages(description, catalog, sounds))
    except Exception as e:
        logger.warning("vibe generation call failed: %s", e)
        raise VibeError(f"The generation model call failed: {e}") from e

    data = parse_draft_json(raw)

    name = _sanitize_name(str(data.get("name") or "")) or "custom_personality"
    instructions = str(data.get("instructions") or "").strip()
    greeting = str(data.get("greeting") or "").strip()
    enable_tools = [t for t in (data.get("enable_tools") or []) if isinstance(t, str) and t in catalog_names]
    # De-duplicate, preserving order.
    enable_tools = list(dict.fromkeys(enable_tools))

    behaviors: List[NewBehavior] = []
    seen: set[str] = set()
    # Maps the model's raw behavior name -> the prefixed tool name it becomes, so the
    # instructions (which reference the raw names) can be rewritten to match the registry.
    renames: Dict[str, str] = {}
    n_repaired = 0
    n_failed = 0
    for raw_behavior in (data.get("new_behaviors") or [])[:MAX_NEW_BEHAVIORS]:
        if not isinstance(raw_behavior, dict):
            continue
        raw_name = str(raw_behavior.get("name") or "behavior")
        prefixed = _sanitize_name(f"{name}_{raw_name}") or _sanitize_name(f"{name}_behavior")
        base = prefixed
        suffix = 2
        while prefixed in seen:
            prefixed = f"{base}_{suffix}"
            suffix += 1
        seen.add(prefixed)
        for variant in (raw_name, _sanitize_name(raw_name)):
            if variant and variant != prefixed:
                renames[variant] = prefixed

        desc = str(raw_behavior.get("description") or "")
        source = str(raw_behavior.get("rmscript") or "")
        final_source, result, attempts = _validate_and_repair(source, complete)
        if result.success:
            final_source = _ensure_description_line(final_source, desc)
            result = compile_script(final_source)
        compiled_ok = bool(result.success)
        if attempts:
            n_repaired += 1
        if not compiled_ok:
            n_failed += 1

        behaviors.append(
            NewBehavior(
                name=prefixed,
                description=(result.description or desc or "").strip(),
                source=final_source,
                compiled_ok=compiled_ok,
                warnings=[getattr(w, "message", str(w)) for w in getattr(result, "warnings", [])],
            )
        )
        logger.info(
            "event=vibe_behavior name=%s compiled_ok=%s repair_attempts=%d errors=%d",
            prefixed,
            compiled_ok,
            attempts,
            len(getattr(result, "errors", [])),
        )

    logger.info(
        "event=vibe_generate name=%s behaviors=%d repaired=%d failed=%d enabled_tools=%d",
        name,
        len(behaviors),
        n_repaired,
        n_failed,
        len(enable_tools),
    )

    # The model refers to its behaviors by the names it invented; the registry
    # knows them by their prefixed names. Rewrite so the prompt names real tools.
    instructions = _apply_renames(instructions, renames)
    greeting = _apply_renames(greeting, renames)

    return VibeDraft(
        name=name,
        instructions=instructions,
        greeting=greeting,
        enable_tools=enable_tools,
        new_behaviors=behaviors,
    )


def commit_draft(draft: Dict[str, Any]) -> str:
    """Persist a (possibly user-edited) draft: write behaviors, then the profile.

    Only behaviors whose source compiles are written to the shared rmscript
    library (prefixed names) and enabled; non-compiling ones are dropped. Returns
    the profile selection string (``user_personalities/<name>``).
    """
    name = _sanitize_name(str(draft.get("name") or ""))
    if not name:
        raise VibeError("invalid_name")
    instructions = str(draft.get("instructions") or "").strip()
    if not instructions:
        raise VibeError("empty_instructions")
    greeting = str(draft.get("greeting") or "").strip()

    enable_tools = [t for t in (draft.get("enable_tools") or []) if isinstance(t, str) and t.strip()]

    written: List[str] = []
    for behavior in draft.get("new_behaviors") or []:
        if not isinstance(behavior, dict):
            continue
        source = str(behavior.get("source") or behavior.get("rmscript") or "")
        if not compile_script(source).success:
            logger.info("event=vibe_commit_skip name=%s reason=compile_failed", behavior.get("name"))
            continue
        saved = write_rmscript_tool(str(behavior.get("name") or ""), source)
        if saved:
            written.append(saved)

    # Preserve order, drop duplicates (a created behavior may also be in enable_tools).
    tool_names = list(dict.fromkeys([*enable_tools, *written]))
    tools_text = "\n".join(tool_names)

    _write_profile(name, instructions, tools_text, None, greeting)
    logger.info("event=vibe_commit name=%s behaviors_written=%d tools=%d", name, len(written), len(tool_names))
    return f"user_personalities/{name}"
