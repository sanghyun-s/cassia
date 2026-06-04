#!/usr/bin/env python3
"""
=============================================================
CASSIA Pass 5 (Stream B polish) — applier script
=============================================================

Surgically patches:
  - backend/main.py
      • SaveUpdateRequest model: adds `also_move_session: bool = False`
      • PATCH /core/saves/{save_id} handler: adds opt-in session-topic
        ripple after the save itself moves
  - backend/static/index.html
      • renderCoreSaves(): wraps the topic dropdown + new checkbox in a
        column container; checkbox sits below the dropdown
      • moveSaveToTopic(): reads the checkbox, sends `also_move_session`
        in the PATCH body, refreshes the sidebar when the response
        confirms `session_also_moved`

Safety:
  - Creates .bak copies before editing
  - Refuses to half-apply: if ANY find-and-replace fails to locate its
    target, ALL changes are rolled back and the script exits non-zero
  - Each edit is checked for "exactly one match" before applying
  - Idempotent: re-running on already-patched files does nothing
    (script detects the post-edit state and exits cleanly)

Run from app2/ project root:
    python3 backend/scripts/apply_pass5.py
"""

from pathlib import Path
import shutil
import sys
import re


# Resolve project root (app2/) regardless of CWD.
SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
MAIN_PY      = PROJECT_ROOT / "backend" / "main.py"
INDEX_HTML   = PROJECT_ROOT / "backend" / "static" / "index.html"


# ════════════════════════════════════════════════════════════════════
#  EDIT DEFINITIONS
# ════════════════════════════════════════════════════════════════════

MAIN_EDIT_1_OLD = '''class SaveUpdateRequest(BaseModel):
    topic_id:    Optional[str] = None
    note:        Optional[str] = None
    clear_topic: bool          = False'''

MAIN_EDIT_1_NEW = '''class SaveUpdateRequest(BaseModel):
    topic_id:          Optional[str] = None
    note:              Optional[str] = None
    clear_topic:       bool          = False
    also_move_session: bool          = False'''

# Anchor that proves Pass 5 has already been applied to main.py.
MAIN_EDIT_1_DONE_MARKER = "also_move_session: bool          = False"


MAIN_EDIT_2_OLD = '''    try:
        update_save_topic(save_id, target_topic, note=body.note)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "updated", "save_id": save_id, "topic_id": target_topic}'''

MAIN_EDIT_2_NEW = '''    try:
        update_save_topic(save_id, target_topic, note=body.note)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Pass 5 (Stream B polish): opt-in ripple — when also_move_session=True,
    # also move the originating chat session to the same topic. Silent skip
    # if the save has no source_session_id (e.g. upload saves) or the source
    # session no longer exists / no longer belongs to the user.
    session_also_moved = False
    if body.also_move_session:
        source_session_id = existing.get("source_session_id")
        if source_session_id and session_belongs_to_user(source_session_id, current_user.user_id):
            try:
                if update_session_topic(source_session_id, target_topic):
                    session_also_moved = True
            except Exception as e:
                print(f"[main] also_move_session ripple failed for {source_session_id}: {e}")

    return {
        "status":             "updated",
        "save_id":            save_id,
        "topic_id":           target_topic,
        "session_also_moved": session_also_moved,
    }'''

MAIN_EDIT_2_DONE_MARKER = "Pass 5 (Stream B polish): opt-in ripple"


INDEX_EDIT_1_OLD = '''        <div class="core-save-foot">
          <select class="core-save-move" onchange="moveSaveToTopic('${s.save_id}', this.value)" title="Move to topic">
            ${topicOptions(s.topic_id)}
          </select>
          <button class="core-save-archive" onclick="archiveCoreSave('${s.save_id}')" title="Remove from core">Archive</button>
        </div>'''

INDEX_EDIT_1_NEW = '''        <div class="core-save-foot">
          <div style="display:flex;flex-direction:column;align-items:flex-start;gap:4px;flex:1;">
            <select class="core-save-move" onchange="moveSaveToTopic('${s.save_id}', this.value)" title="Move to topic">
              ${topicOptions(s.topic_id)}
            </select>
            <label style="display:flex;align-items:center;gap:6px;font-size:11px;opacity:0.7;cursor:pointer;user-select:none;">
              <input type="checkbox" id="alsomove-${s.save_id}" style="margin:0;cursor:pointer;" />
              Also move source session
            </label>
          </div>
          <button class="core-save-archive" onclick="archiveCoreSave('${s.save_id}')" title="Remove from core">Archive</button>
        </div>'''

INDEX_EDIT_1_DONE_MARKER = 'id="alsomove-${s.save_id}"'


INDEX_EDIT_2_OLD = '''async function moveSaveToTopic(saveId, topicValue) {
  const body = (topicValue === '__none__')
    ? { clear_topic: true }
    : { topic_id: topicValue };
  try {
    const r = await apiFetch(`/core/saves/${saveId}`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      showToast('error', 'Move failed', err.detail || 'Server error');
      return;
    }
    showToast('core', 'Save moved', topicValue === '__none__' ? 'Unsorted' : 'topic updated');
    await loadCoreTopics();
  } catch (e) {
    showToast('error', 'Move failed', e.message || 'Network error');
  }
}'''

INDEX_EDIT_2_NEW = '''async function moveSaveToTopic(saveId, topicValue) {
  const alsoMove = document.getElementById(`alsomove-${saveId}`)?.checked || false;
  const body = (topicValue === '__none__')
    ? { clear_topic: true, also_move_session: alsoMove }
    : { topic_id: topicValue, also_move_session: alsoMove };
  try {
    const r = await apiFetch(`/core/saves/${saveId}`, {
      method:  'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      showToast('error', 'Move failed', err.detail || 'Server error');
      return;
    }
    const data         = await r.json().catch(() => ({}));
    const sessionMoved = data.session_also_moved === true;
    const where        = topicValue === '__none__' ? 'Unsorted' : 'topic updated';
    showToast('core', 'Save moved', sessionMoved ? `${where} · session also moved` : where);
    if (sessionMoved) {
      await loadSessions();   // refresh sidebar so session-topic groups update
    }
    await loadCoreTopics();
  } catch (e) {
    showToast('error', 'Move failed', e.message || 'Network error');
  }
}'''

INDEX_EDIT_2_DONE_MARKER = "const alsoMove = document.getElementById"


EDITS = [
    {
        "file":         MAIN_PY,
        "label":        "main.py · SaveUpdateRequest model",
        "old":          MAIN_EDIT_1_OLD,
        "new":          MAIN_EDIT_1_NEW,
        "done_marker":  MAIN_EDIT_1_DONE_MARKER,
    },
    {
        "file":         MAIN_PY,
        "label":        "main.py · PATCH /core/saves/{save_id} handler",
        "old":          MAIN_EDIT_2_OLD,
        "new":          MAIN_EDIT_2_NEW,
        "done_marker":  MAIN_EDIT_2_DONE_MARKER,
    },
    {
        "file":         INDEX_HTML,
        "label":        "index.html · renderCoreSaves foot block (dropdown + checkbox)",
        "old":          INDEX_EDIT_1_OLD,
        "new":          INDEX_EDIT_1_NEW,
        "done_marker":  INDEX_EDIT_1_DONE_MARKER,
    },
    {
        "file":         INDEX_HTML,
        "label":        "index.html · moveSaveToTopic function",
        "old":          INDEX_EDIT_2_OLD,
        "new":          INDEX_EDIT_2_NEW,
        "done_marker":  INDEX_EDIT_2_DONE_MARKER,
    },
]


# ════════════════════════════════════════════════════════════════════
#  APPLIER
# ════════════════════════════════════════════════════════════════════

def main() -> int:
    print("=" * 64)
    print("  CASSIA — Pass 5 (Stream B polish) applier")
    print("=" * 64)
    print()

    for f in (MAIN_PY, INDEX_HTML):
        if not f.exists():
            print(f"✗  Required file missing: {f}")
            print(f"   (resolved from script location: {SCRIPT_DIR})")
            return 1

    # Plan: read each file once, attempt all edits in memory, write back
    # only after every edit has succeeded across all files. This is the
    # "all or nothing" guarantee.

    files_state = {
        MAIN_PY:    {"original": MAIN_PY.read_text(),    "updated": None, "edits_applied": 0, "edits_skipped": 0},
        INDEX_HTML: {"original": INDEX_HTML.read_text(), "updated": None, "edits_applied": 0, "edits_skipped": 0},
    }

    # Seed updated buffer with original content
    for state in files_state.values():
        state["updated"] = state["original"]

    print("Applying edits ...")
    print()

    for edit in EDITS:
        f             = edit["file"]
        label         = edit["label"]
        old           = edit["old"]
        new           = edit["new"]
        done_marker   = edit["done_marker"]
        buffer        = files_state[f]["updated"]

        # Idempotency check: if the post-edit marker is already present,
        # this edit was already applied earlier.
        if done_marker in buffer:
            print(f"  · {label}")
            print(f"    already applied (marker detected) — skipping")
            files_state[f]["edits_skipped"] += 1
            continue

        # Locate the OLD block
        count = buffer.count(old)
        if count == 0:
            print(f"  ✗ {label}")
            print(f"    OLD block not found in {f.name}.")
            print(f"    Either the file has been modified outside this script, or the")
            print(f"    source has drifted from the version this script was built for.")
            print(f"    No files have been changed. Inspect manually and try again.")
            return 1
        if count > 1:
            print(f"  ✗ {label}")
            print(f"    OLD block found {count} times in {f.name} (expected exactly 1).")
            print(f"    The match is ambiguous; aborting before changes are written.")
            return 1

        # Single match — safe to replace
        files_state[f]["updated"] = buffer.replace(old, new, 1)
        files_state[f]["edits_applied"] += 1
        print(f"  ✓ {label}")

    print()

    # Anything to write?
    files_with_changes = [
        f for f, st in files_state.items()
        if st["edits_applied"] > 0 and st["updated"] != st["original"]
    ]

    if not files_with_changes:
        print("Nothing to write — all edits were already applied.")
        print("Pass 5 is in place on this codebase. No action taken.")
        return 0

    # Back up + write
    print("Writing files (with .bak safety copies) ...")
    for f in files_with_changes:
        bak = f.with_suffix(f.suffix + ".bak")
        shutil.copy2(f, bak)
        f.write_text(files_state[f]["updated"])
        applied = files_state[f]["edits_applied"]
        skipped = files_state[f]["edits_skipped"]
        suffix  = f" ({skipped} edit(s) already in place)" if skipped else ""
        print(f"  ✓ {f.relative_to(PROJECT_ROOT)} — {applied} edit(s) applied{suffix}")
        print(f"    backup at {bak.relative_to(PROJECT_ROOT)}")

    print()
    print("Done. Next steps:")
    print("  1. Optional: bump banner v2.12.0 → v2.12.1 in main.py")
    print("       sed -i '' 's/v2\\.12\\.0/v2.12.1/g' backend/main.py")
    print("       sed -i '' 's/\"2\\.12\\.0\"/\"2.12.1\"/g' backend/main.py")
    print("  2. Syntax-check main.py:")
    print("       python3 -c \"import ast; ast.parse(open('backend/main.py').read()); print('OK')\"")
    print("  3. Restart the server and smoke test in the browser.")
    print()
    print("If anything is off, restore from the .bak files:")
    print("  cp backend/main.py.bak backend/main.py")
    print("  cp backend/static/index.html.bak backend/static/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
