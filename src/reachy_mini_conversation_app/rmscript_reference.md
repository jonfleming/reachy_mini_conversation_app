<!--
  Vendored copy of rmscript_reference_doc.md from the rmscript compiler repo
  (pinned dependency, tag v0.1.3). Fed to the "vibe-create" LLM as the language
  spec. The `rmscript` package is installed from git and does not ship this doc,
  so it is copied here. Re-sync when bumping the rmscript pin.
-->

# rmscript - Kid-Friendly Robot Programming

> **For developers:** See [README.md](README.md) for installation, API documentation, and compiler architecture.

rmscript is a natural language-inspired programming language designed to make robot programming accessible and fun for children.
It compiles to an intermediate representation (IR) that can be executed by different adapters on the Reachy Mini robot.

## Example Usage

Create a file `hello.rmscript`:

```rmscript
"Wave hello to someone"
antenna up
wait 1s
antenna down
look left
look right
look center
```

Test the script using the provided example runner (after starting the reachy-mini-daemon):

```bash
python examples/run_rmscript.py path/to/hello.rmscript
```

**Note:** The `run_rmscript.py` file is located in the `examples/` directory of the rmscript package.


## Language Syntax

### File Structure

Every rmscript file has a simple structure:

```rmscript
"Wave hello to someone"
# Your commands here
look left
wait 1s
```

**Description line (optional):**
- A quoted string (single or double quotes) on the first non-blank, non-comment line
- If omitted, a default description is used: `"This is a Reachy Mini Script"`
- If a quoted string appears anywhere else in the script, it will cause an error

```rmscript
# Valid: with description
"My robot dance"
look left
body right

# Valid: without description (uses default)
look left
body right

# Invalid: misplaced description
look left
"This will cause an error"
body right
```

### Basic Commands

```rmscript
# Comments start with #

# Movement commands
look left
body right
antenna up
head forward 10

# Reset all DOFs to a neutral base pose
reset

# Wait command
wait 2s
wait 0.5s

# Camera command
picture

# Sound playback
play mysound
play othersound pause
```

### Case Insensitivity

rmscript is case-insensitive for keywords:

```rmscript
LOOK left    # Same as "look left"
Look Left    # Same as "look left"
WAIT 1s      # Same as "wait 1s"
```

## Movement Commands

### Look (Head Orientation)

Control the robot's head orientation (pitch and yaw). `look` only moves the
**head**, relative to the body's current facing direction — it never drives the
body yaw motor. So after a `body`, a `look` is measured from the rotated body
axis (e.g. `body right 70` then `look right 20` ends up 90° right in the world).

```rmscript
look left          # Turn head left (30° default)
look right 45      # Turn head right 45°
look up           # Tilt head up (30° default)
look down 20      # Tilt head down 20°
look center       # Return to center position

# Synonyms
look straight     # Same as center
look neutral      # Same as center
```

**Physical Limits (enforced — out-of-range angles are clamped, not compensated):**
- Pitch (up/down): ±40°
- Yaw (left/right): ±65° relative to the body axis (e.g. `look right 80` → 65°)

### Body (Body Rotation)

Rotate the robot's body (the head rotates together with the body):

```rmscript
body left         # Rotate body and head left (30° default)
body right 90     # Rotate body and head right 90°
body center       # Face forward
```

**Note:** The `body` command rotates both the body yaw and the head yaw together, since the body carries the head.

The head's `look` offset is **kept** across body moves: if the head is looking
60° left and you then `body left 10`, the head stays 60° left of the body (70°
in the world), it does not snap back to the body axis. `look` commands, by
contrast, are absolute per line — `look up` after `look left` resets the yaw.

**Physical Limits:**
- Body yaw: ±160° (safe limit: ±120°)

### Antenna

Control the antenna positions using multiple syntaxes:

**Clock Position (Numeric 0-12):**
```rmscript
antenna both 0       # 0 o'clock = 0° (straight up)
antenna both 3       # 3 o'clock = 90° (external/right)
antenna both 6       # 6 o'clock = 180° (straight down)
antenna both 9       # 9 o'clock = -90° (internal/left)
antenna left 4.5     # Left antenna to 4.5 o'clock (135°)
```

**Clock Keywords:**
```rmscript
antenna both high    # 0° (high position)
antenna both ext     # 90° (external)
antenna both low     # 180° (low position)
antenna both int     # -90° (internal)
```

**Directional Keywords (Natural Language):**
```rmscript
antenna both up      # 0° (up)
antenna both right   # 90° (right/external)
antenna both down    # 180° (down)
antenna both left    # -90° (left/internal)

# Individual antenna control
antenna left up      # Left antenna pointing up
antenna right down   # Right antenna pointing down

# Even in potentially confusing cases, it works naturally:
antenna left left    # Left antenna pointing left (-90°)
antenna right right  # Right antenna pointing right (90°)
```

**Physical Limits:**
- Antenna angle: ±180° (safe limit: ±120°)

### Head Translation

Move the head forward/back/left/right/up/down in space:

```rmscript
head forward 10    # Move head forward 10mm
head back 5        # Move head back 5mm
head backward 5    # Same as "back" (synonym)
head backwards 5   # Same as "back" (synonym)
head left 8        # Move head left 8mm
head right 8       # Move head right 8mm
head up 5          # Move head up 5mm
head down 3        # Move head down 3mm
```

**Physical Limits:**
- X (forward/back): ±30mm
- Y (left/right): ±30mm
- Z (up/down): +20mm / -40mm

### Tilt (Head Roll)

Tilt the head side-to-side:

```rmscript
tilt left 15       # Tilt head left
tilt right 15      # Tilt head right
tilt center        # Return to level
```

**Physical Limits:**
- Roll: ±40°

### Reset

Return every degree of freedom to its neutral base pose:

```rmscript
reset             # Back to a neutral pose on all DOFs
```

`reset` takes **no arguments**. It is shorthand for:

```rmscript
look center and tilt center and body center and antenna both up
```

All movements happen simultaneously, in a single merged command. Trying to
add an argument (e.g. `reset left`) is a compilation error.

### Wait

Pause between movements:

```rmscript
wait 1s           # Wait 1 second
wait 0.5s         # Wait 0.5 seconds
wait 2.5s         # Wait 2.5 seconds
```

**Important:** The `s` suffix is **required** for consistency. `wait 1` will produce a compilation error.

### Picture

Take a picture with the robot's camera:

```rmscript
picture           # Take a picture
```

The picture command captures a frame from the camera and returns it as a base64-encoded image.

**How it works:**

1. **During execution**: The `picture` command is queued as a movement (instant duration: 0.01s)
2. **Capture timing**: Picture is captured at the right moment in the movement sequence
3. **File storage**: Pictures are automatically saved to `/tmp/reachy_picture_YYYYMMDD_HHMMSS_microseconds.jpg`
4. **Color handling**: Images are captured in RGB format with proper color conversion

**Single picture (LLM-compatible):**
```rmscript
"Check behind by taking a picture"
body left maximum
wait 0.5s
picture
wait 0.5s
body center
```

This script:
- Turns the robot to look behind (120° left)
- Waits for movement to stabilize
- Captures a picture at the right moment
- Returns to center position
- The LLM receives the picture and can describe what it sees

**Important timing notes:**
- Add `wait` commands before `picture` to let movements complete
- The tool automatically waits for all movements + picture capture before returning
- Pictures are captured when the movement queue reaches them (not immediately)

**Multiple pictures:**
```rmscript
"Look around and take pictures"
look left
wait 0.5s
picture
look right
wait 0.5s
picture
look center
```

Each `picture` command captures a separate image. 
For single-picture scripts, the image is returned in Camera-compatible format (`b64_im`) for LLM integration. 
For multi-picture scripts, images are returned as an array.

**Use with `run_rmscript.py`:**

When testing scripts with `run_rmscript.py`, pictures are:
- Saved to `/tmp` with timestamped filenames
- Logged with full paths for easy access
- Displayed in the execution summary
- 

### Play Sound

Play sound files (.wav, .mp3, .ogg, .flac) during script execution:

```rmscript
play soundname         # Play sound in background (async, continues immediately)
play soundname pause   # Wait for sound to finish before continuing (blocking)
play soundname 5s      # Play sound for exactly 5 seconds (blocking)
```

The script automatically searches for sound files in this order:
1. **Directory containing the .rmscript file** (highest priority - co-located sounds)
2. Current working directory
3. `sounds/` subdirectory

**Asynchronous playback (default):**
```rmscript
play intro            # Starts playing, script continues immediately
look left
wait 1s
```
The sound plays in the background while movements execute.

**Blocking playback (wait for sound to finish):**
```rmscript
play mysound pause    # Waits for sound to finish
# OR use synonyms:
play mysound fully
play mysound wait
play mysound block
play mysound complete
```

The script pauses until the sound finishes playing, then continues.

**Duration-limited playback:**
```rmscript
play mysound 10s      # Play sound for exactly 10 seconds (blocks for 10s)
```

Plays the sound for the specified duration. If the sound is shorter, it will finish early. If longer, it will be cut off.

### Loop Sound

Loop a sound file repeatedly for a specified duration:

```rmscript
loop soundname        # Loop sound for 10 seconds (default)
loop soundname 5s     # Loop sound for 5 seconds
loop soundname 30s    # Loop sound for 30 seconds
```

The loop command automatically repeats the sound until the duration expires. This is useful for background music or ambient sounds.

**Example use case:**
```rmscript
"Greet with sound and movement"
play hello pause      # Play greeting sound fully
wait 0.5s
antenna both up       # Wave antennas
wait 1s
antenna both down
```

**Sound files:**
- File extensions: `.wav`, `.mp3`, `.ogg`, `.flac`
- Example: `play hello` looks for `hello.wav`, `hello.mp3`, etc.
- **Best practice**: Place sound files in the same directory as your .rmscript file
- Alternative locations: working directory or `sounds/` subdirectory

## Advanced Features

### Keyword Reuse with `and`

Chain multiple directions with the same action keyword:

```rmscript
# Reuse "look" keyword
look left and up 25
# → Equivalent to: look left + look up 25
# → Merged into single command

# Different keywords - no reuse
body left and look right
# → body left + look right
# → Two separate commands merged
```

This creates more natural, flowing descriptions while optimizing execution.

### Qualitative Strength

Use descriptive words instead of numbers - works for both angles and distances:

```rmscript
# 5 levels of strength - values are context-aware!

# Examples:
body left tiny          # 10° (body yaw can handle larger movements)
look up tiny            # 5° (head pitch limited by cone constraint)
head forward tiny       # 2mm

body left maximum       # 120° (body yaw safe maximum)
look up maximum         # 38° (respects ±40° pitch limit)
look left maximum       # 60° (respects ±65° body-head differential)
head forward maximum    # 28mm (under 30mm limit)
```

**Available Qualitative Keywords:**
- **VERY_SMALL**: minuscule, mini, verysmall, tiny
- **SMALL**: little, slightly, small, alittle
- **MEDIUM**: medium, normal, regular, standard, normally
- **LARGE**: lot, big, large, very, alot, huge, strong, strongly
- **VERY_LARGE**: verybig, enormous, verylarge, maximum

**Context-Aware Values:**

TODO: check physical limits and adjust values accordingly.

The same qualitative keyword maps to different values depending on the movement type, respecting physical limits:

| Keyword | VERY_SMALL | SMALL | MEDIUM | LARGE | VERY_LARGE |
|---------|------------|-------|--------|-------|------------|
| **Body Yaw (body)** | 10° | 30° | 60° | 90° | 120° |
| **Head Pitch/Roll (look up/down, tilt)** | 5° | 10° | 20° | 30° | 38° |
| **Head Yaw (look left/right)** | 5° | 15° | 30° | 45° | 60° |
| **Head Translation (head forward/back/etc)** | 2mm | 5mm | 10mm | 20mm | 28mm |
| **Antennas** | 10° | 30° | 60° | 90° | 110° |

**Note:** These values are carefully chosen to stay within the robot's physical limits while maximizing safe range of motion.

### Duration Keywords

Use descriptive speed words:

```rmscript
look left superfast    # 0.2 seconds
look right fast        # 0.5 seconds
look up slow           # 2.0 seconds
look up slowly         # 2.0 seconds (synonym for slow)
look down superslow    # 3.0 seconds
```

Combine with 'and':

```rmscript
body left and look right fast
# Both movements complete in 0.5 seconds
```

### Repeat Blocks

Repeat a sequence of commands:

```rmscript
repeat 3
    look left
    wait 0.5s
    look right
    wait 0.5s

# Nested repeat blocks work too
repeat 2
    antenna up
    repeat 3
        look left
        look right
    antenna down
```

**Indentation:** Use spaces or tabs consistently (tabs = 4 spaces).

### Combining Movements

Combine multiple movements into a single smooth motion:

```rmscript
# All happen simultaneously
antenna both up and look up 25 and body left 30
```

This merges into a single `goto_target()` call with all parameters.

**Important:** The `and` keyword can only combine movement commands (body, look, head, tilt, antenna). 
You **cannot** combine movements with control commands (picture, play, loop, wait) using `and`. Use separate lines instead:

```rmscript
# ❌ ERROR - Cannot combine movement with picture
look left and picture

# ✓ CORRECT - Use separate lines
look left
wait 0.5s
picture

# ❌ ERROR - Cannot combine movement with play
body right and play mysound

# ✓ CORRECT - Use separate lines
body right
play mysound
```




## Examples

### Example 1: Simple Greeting

```rmscript
"Greet someone warmly"
# Wave with antennas
antenna up
wait 0.5s
antenna down
wait 0.5s

# Nod
look down 20
wait 0.3s
look up 20
wait 0.3s
look center
```

### Example 2: Search Pattern

```rmscript
"Look around to search for something"
# Scan left to right
look left 45
wait 1s
look center
wait 0.5s
look right 45
wait 1s
look center

# Check up and down
look up 30
wait 0.5s
look down 30
wait 0.5s
look center
```

### Example 3: Dance Choreography

```rmscript
"Perform a fun dance routine"
# Opening pose
antenna both up and look up 25
wait 1s

# Main sequence
repeat 2
    # Move left
    body left 30 and look right 20
    wait 0.5s

    # Move right
    body right 30 and look left 20
    wait 0.5s

# Ending pose
body center and look center and antenna down
```

### Example 4: Using Qualitative Strength

```rmscript
"Wave shyly at someone"
# Small movements
look down slightly
antenna left up a little
wait 1s
antenna left down
look center
```

### Example 5: Complex Combination

```rmscript
"Show excitement when greeting"
# Quick movements
repeat 3
    antenna both up superfast
    antenna both down superfast

# Energetic looking around
look left and up fast
wait 0.2s
look right and up fast
wait 0.2s
look center slow
```

## Error Handling

### Compilation Errors

Errors prevent code generation:

```rmscript
# Invalid keyword
jump up
```
**Output:** `❌ Line 1: Unexpected token: 'jump'`

```rmscript
# Invalid direction for keyword
body up
```
**Output:** `❌ Line 1: Invalid direction 'up' for keyword 'body'`

```rmscript
# Missing indentation
repeat 3
look left
```
**Output:** `❌ Line 2: Expected indented block after 'repeat'`

### Compilation Warnings

Warnings allow compilation but alert to potential issues:

```rmscript
# Exceeds safe range
body left 200
```
**Output:** `⚠️  Line 1: Body yaw 200.0° exceeds limit (±160.0°), clamped to 160.0°`

```rmscript
# Exceeds physical limit
look up 50
```
**Output:** `⚠️  Line 1: Head pitch 50.0° exceeds limit (±40.0°), clamped to 40.0°`

### Handling Errors in Code

```python
tool = compiler.compile(source)

if not tool.success:
    print("Compilation failed!")
    for error in tool.errors:
        print(f"  ❌ Line {error.line}: {error.message}")
    exit(1)

if tool.warnings:
    print("Compilation succeeded with warnings:")
    for warning in tool.warnings:
        print(f"  ⚠️  Line {warning.line}: {warning.message}")

# Safe to execute
tool.execute(mini)
```

## Tips and Best Practices

### 1. Use Comments

```rmscript
# Good: explain what you're doing
# Opening sequence: get attention
antenna up
wait 1s

# Main behavior: scan the room
look left 45
wait 1s
look right 45
```

### 2. Use Descriptive Tool Names

```python
# Good




# Avoid



```

### 3. Break Complex Behaviors into Steps

```rmscript
# Good: readable steps
antenna up
wait 1s
look left
wait 0.5s
look right
wait 0.5s
look center

# Avoid: too compressed
antenna up and look left and wait 1s and look right
```

### 4. Use Repeat for Patterns

```rmscript
# Good: use repeat
repeat 3
    antenna up
    antenna down

# Avoid: repetitive
antenna up
antenna down
antenna up
antenna down
antenna up
antenna down
```

### 5. Test with Small Values First

```rmscript
# Start conservative
look left 10
body right 15

# Then increase if needed
look left 45
body right 90
```

## Physical Safety Limits

rmscript validates all movements against these limits:

| Movement | Limit | Enforcement |
|----------|-------|------------------|
| Body yaw (body) | ±160° | Clamped |
| Head yaw (look left/right) | ±65° relative to body | Clamped |
| Head pitch (look up/down) | ±40° | Clamped |
| Head roll (tilt) | ±40° | Clamped |
| Antenna | ±90° (safe ±65°) | Warning only |
| Head X (forward/back) | ±50mm typical | Warning only |
| Head Y (left/right) | ±50mm typical | Warning only |
| Head Z (up/down) | +20mm / -30mm typical | Warning only |

Rotation limits (body / look / tilt) are **enforced at compile time**: an
out-of-range angle is clamped to the limit and a warning is emitted (e.g.
`look right 80` compiles to a 65° head turn). Translations and antenna angles
currently emit warnings only.

## Default Values

When values aren't specified:

| Parameter | Default |
|-----------|---------|
| Angle (look, body, tilt) | 30° |
| Distance (head translation) | 10mm |
| Antenna angle | 45° |
| Duration | 1.0s |

**Qualitative Strength Values:**

| Level | Keywords | Angle | Distance |
|-------|----------|-------|----------|
| VERY_SMALL | tiny, minuscule, mini, verysmall | 5° | 2mm |
| SMALL | little, slightly, small, alittle | 15° | 5mm |
| MEDIUM | medium, normal, regular, standard, normally | 30° | 10mm |
| LARGE | strong, lot, big, large, very, alot, huge, strongly | 45° | 20mm |
| VERY_LARGE | enormous, verybig, verylarge, maximum | 60° | 30mm |

## Troubleshooting

### Issue: "Inconsistent indentation"

**Cause:** Mixing tabs and spaces, or inconsistent indentation levels.

**Solution:** Use only spaces or only tabs (not mixed). Ensure nested blocks are indented consistently.

```rmscript
# Bad: mixed tabs and spaces
repeat 3
    look left      # 4 spaces
→   look right     # 1 tab (shows as →)

# Good: consistent spaces
repeat 3
    look left      # 4 spaces
    look right     # 4 spaces
```

### Issue: "Expected indented block after 'repeat'"

**Cause:** No indentation after `repeat`.

**Solution:** Indent the repeat block body.

```rmscript
# Bad
repeat 3
look left

# Good
repeat 3
    look left
```

### Issue: Generated code has unexpected angles

**Cause:** Sign convention confusion (left/right).

**Solution:** Remember: `left` = positive yaw, `right` = negative yaw in the generated code. `up` = negative pitch, `down` = positive pitch. This matches the robot's actual coordinate system.



