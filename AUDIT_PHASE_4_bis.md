# Handoff Prompt — Verify Current State and Continue Phase 4

You are taking over an existing Home Assistant custom integration project named `hikvision_next_level`.

The repository contains the full project context and previous phase reports.

Before changing anything, read these files in this order:

1. `PROJECT_REFERENCE.md`
2. `AUDIT_PHASE_0.md`
3. `PHASE_1_REPORT.md`
4. `PHASE_2_REPORT.md`
5. `PHASE_3_REPORT.md`

The current development phase is:

```text
Phase 4 — Automatic Capability Discovery
```

Another coding agent may already have partially implemented Phase 4 before the previous workspace ran out of credits.

Your first task is therefore NOT to restart Phase 4 from scratch.

Your first task is to determine exactly what has already been implemented, verify whether it is correct, and only then continue from the actual repository state.

---

# 1. Inspect the repository state

Start with:

```text
git status
git branch --show-current
git log --oneline --decorate -15
git diff
git diff --cached
```

Identify:

* current branch;
* uncommitted changes;
* staged changes;
* last completed phase;
* whether Phase 4 work is already present;
* any files partially modified by the previous agent.

Do not discard or overwrite existing work.

Do not reset the repository.

Treat existing uncommitted code as potentially valuable until inspected.

---

# 2. Identify Phase 4 implementation already present

Search specifically for capability-related code.

Look for:

```text
capability
capabilities
discovery
supported
unsupported
unknown
NumericCapability
SelectCapability
PTZ
white_light
smart_hybrid
day_night
WDR
BLC
HLC
```

Inspect any newly created or modified files.

Determine whether the previous agent already implemented:

* a central capability model;
* capability discovery;
* capability probing;
* per-device or per-channel capability storage;
* NVR channel capability handling;
* `opt=` parsing;
* numeric min/max/step parsing;
* capability caching;
* rediscovery support;
* tests;
* documentation/report changes.

Do not assume implementation quality from filenames alone.

Read the code.

---

# 3. Verify that previous phases were not broken

Before continuing Phase 4, confirm that the existing architecture from Phases 1–3 is still intact.

Required invariants:

## Phase 1

* Home Assistant domain remains:

```text
hikvision_next
```

* existing unique IDs are unchanged;
* existing entity IDs are unchanged unless explicitly migrated;
* setup/unload/reload lifecycle remains coherent;
* `EventNotificationsView` is registered at integration level, not once per ConfigEntry.

## Phase 2

The event path must remain conceptually:

```text
transport
→ HikvisionEventPayloadParser
→ HikvisionEventParser
→ HikvisionEvent
→ HikvisionEventProcessor
```

The processor must remain independent from aiohttp.

## Phase 3

The raw compatibility listener must remain conceptually:

```text
asyncio.start_server
→ minimal HTTP parsing
→ existing payload parser
→ existing event parser
→ existing processor
```

It must still:

* accept HTTP/1.1 without `Host`;
* listen on the dedicated legacy event port;
* not depend on aiohttp;
* not duplicate XML or multipart parsing;
* preserve the existing aiohttp transport;
* remain bounded by header/body/time limits.

If the current Phase 4 changes accidentally modified any of these areas, flag it before continuing.

---

# 4. Validate existing Phase 4 code before extending it

For every Phase 4 component already implemented, verify:

## Capability model

It should be centralized and typed.

It must not rely primarily on model-name checks.

Capabilities should be attached at the correct scope:

```text
NVR-level capabilities
vs
camera/channel-level capabilities
```

A mixed-camera NVR must not incorrectly inherit one channel's capabilities across all channels.

---

## Discovery

Discovery should use the existing Hikvision ISAPI client and should not duplicate:

* authentication;
* request handling;
* timeout handling;
* generic XML HTTP logic.

Feature detection may combine:

```text
capability endpoints
feature-specific capability endpoints
safe endpoint probing
```

Do not assume one global `/capabilities` endpoint is authoritative.

---

## Unknown vs unsupported

Where HTTP/API semantics require it, distinguish:

```text
SUPPORTED
UNSUPPORTED
UNKNOWN
```

In particular:

```text
403 Forbidden
```

must not automatically mean:

```text
unsupported
```

A 404 may indicate unsupported where appropriate.

---

## Select capabilities

If Hikvision XML contains:

```xml
opt="auto,day,night"
```

the allowed options should be retained for future entities.

Do not reduce this to a simple boolean if the values are available.

---

## Numeric capabilities

If Hikvision exposes:

```text
min
max
step
```

retain those values.

Future Home Assistant number entities must not use guessed ranges.

---

## Failure isolation

A failure discovering one capability must not break:

```text
camera
events
snapshots
other channels
entire NVR setup
```

Capability discovery must degrade gracefully.

---

## Existing features

Do not remove existing entities merely because the new capability discovery returns `UNKNOWN`.

Phase 4 must remain conservative for historical functionality.

---

# 5. Inspect all Phase 4 tests already written

Read existing tests before adding more.

Determine what is already covered.

At minimum Phase 4 should eventually cover:

```text
fixed camera
PTZ camera
ColorVu / Smart Hybrid Light camera
/SL camera
NVR with mixed channel capabilities
403 permission case
404 unsupported case
malformed capability XML
select opt parsing
numeric min/max/step parsing
partial capability-discovery failure
```

Do not create duplicate tests if equivalent coverage already exists.

---

# 6. Execute the validation that is possible locally

Run:

```text
python -m compileall -q custom_components tests
git diff --check
```

If pytest is available:

```text
python -m pytest -q
```

If pytest is unavailable, do not spend excessive time trying to rebuild a large historical Home Assistant test environment.

The previous project reports already document dependency-resolution problems.

Do not silently modify dependency pins merely to make pytest install.

If you identify a clearly isolated test-environment fix, document it separately rather than mixing it into capability discovery.

---

# 7. Use the real Home Assistant development instance when useful

This project is automatically synchronized over SFTP to a Home Assistant development instance.

The local Git repository remains the source of truth.

Do not edit only the remote Home Assistant copy.

When runtime validation is useful:

1. modify code locally;
2. save/sync it to HA;
3. reload the integration or restart Home Assistant only when required;
4. inspect `hikvision_next` DEBUG logs;
5. compare detected capabilities against real Hikvision hardware.

Do not change camera configuration merely to test discovery.

Discovery should be read-only.

---

# 8. Current Phase 4 target

When Phase 4 is complete, the project should have a centralized capability system able to represent, where reliably discoverable:

## Streams

```text
main stream
sub stream
third stream
```

## PTZ

```text
PTZ support
preset support
```

## Supplement lighting

```text
IR
white light
Smart Hybrid Light
brightness support
```

## Detection

```text
motion
line crossing
intrusion
human filter
vehicle filter
```

## Day/night

```text
day/night control
supported modes
sensitivity if available
switching delay if available
```

## Image settings

At least discovery architecture for:

```text
brightness
contrast
saturation
sharpness
WDR
BLC
HLC
gain
shutter
noise reduction
defog
```

Only mark features supported when the device/API provides adequate evidence.

## Audio

```text
microphone
speaker
siren
```

## NVR

```text
alarm inputs
soft alarm inputs
```

Do NOT create the user-facing control entities for these features yet.

This phase is discovery only.

---

# 9. Do not overengineer Phase 4

Avoid:

* generic plugin systems;
* large abstract factory hierarchies;
* capability DSLs;
* dozens of tiny files;
* speculative capabilities not required by `PROJECT_REFERENCE.md`;
* rewriting the entire ISAPI client.

Prefer the smallest clean design that supports the required future phases.

---

# 10. Do not add out-of-scope functionality

Do not implement:

```text
PTZ commands
light controls
Day/Night controls
image-setting entities
siren controls
detection sensitivity controls
Soft Alarm triggers
recording browser
ANPR
face recognition
firmware updates
```

Those come later.

---

# 11. Continue from the real current state

After inspection, produce a short internal checklist with three categories:

```text
Already implemented and correct
Implemented but needs correction
Still missing
```

Then continue Phase 4 only for the missing or incorrect parts.

Do not rewrite working implementation simply because you would have designed it differently.

---

# 12. Keep changes efficient

This project previously consumed excessive agent credits.

Work economically.

Do not repeatedly reread large files unless necessary.

Use targeted searches.

Avoid repeating large summaries of project history.

Prefer small coherent edits and validate after each logical change.

Do not produce verbose progress reports unless needed.

---

# 13. Update the Phase 4 report

If `PHASE_4_REPORT.md` already exists, update it.

Otherwise create it.

It must contain:

## Existing work found

What Phase 4 implementation was already present when you took over.

## Corrections made

Any issues you found in the partial implementation.

## Final architecture

Capability model and discovery flow.

## Files changed

Exact list.

## Endpoints used

Table:

```text
Feature | Endpoint | Interpretation
```

## Device/channel scope

How standalone cameras, NVRs and NVR channels are handled.

## Unknown vs unsupported

Document the policy.

## Numeric capabilities

How min/max/step are retained.

## Select capabilities

How `opt=` values are retained.

## Cache strategy

When discovery runs and where results are stored.

## Failure handling

How individual failures are isolated.

## Tests

Tests found, tests added, and tests executed.

## Real hardware validation

If performed:

```text
model
firmware
capabilities detected
unexpected results
```

No credentials.

## Known limitations

Clearly list anything not reliably discoverable yet.

## Phase 5 readiness

Explain whether the capability architecture is ready for the next planned feature phase.

---

# 14. Git safety

Before finishing:

```text
git status
git diff
git diff --check
```

Do not delete unrelated files.

Do not push.

If an existing commit from the previous agent is incomplete, do not rewrite history unless absolutely necessary.

Prefer a new corrective commit.

---

# 15. Completion criteria

Phase 4 is complete only when:

* existing Phase 4 work has been audited;
* broken/incomplete work has been corrected;
* centralized capability model exists;
* discovery is centralized;
* standalone cameras are supported;
* NVR channel-specific capabilities are supported;
* unsupported and unknown are distinguished where needed;
* `opt=` values are retained;
* numeric ranges are retained;
* partial discovery failure does not break device setup;
* no new control entities were added;
* existing entity IDs and unique IDs remain unchanged;
* Phases 1–3 architecture remains intact;
* `PHASE_4_REPORT.md` accurately reflects the final state.

---

# 16. Stop condition

When Phase 4 is complete, stop.

Do not start Phase 5 automatically.

Finish with a concise summary similar to:

```text
Phase 4 takeover complete.

Existing capability work was audited and corrected where necessary.
Automatic capability discovery is now ready for review.

See PHASE_4_REPORT.md.
```
