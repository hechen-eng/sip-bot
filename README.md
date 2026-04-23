# SIP Bot
This bot follows https://docs.livekit.io/agents/start/voice-ai-quickstart/.

To test outbound call, do
```
lk --project <project-name> dispatch create --new-room --agent-name <agent-name> --metadata '{"phone_number": "<your-personal-number>"}'
```

To create agent, do
```
lk agent create
```

After making some changes, do
```
lk agent deploy
```

## Testing rust-sdks / krisp-plugin dylib swaps

This agent can be used as a harness to verify changes to the LiveKit FFI dylib
(`liblivekit_ffi.dylib`) or the Krisp noise-cancellation plugin dylib
(`liblivekit_nc_plugin.dylib`). Rebuild the dylibs locally, swap them into this
venv, and run the agent either against a synthetic audio publisher
(`lk load-test`) or against your own mic via a browser.

### One-time setup

Run all commands from the sip-bot repo root. Set `$WORKSPACE` to the directory
that holds your `rust-sdks` and `krisp-noise-filter` checkouts.

```bash
# Directory containing rust-sdks and krisp-noise-filter (change to your layout)
WORKSPACE=/path/to/workspace

# Swappable dylib paths inside this venv (relative to the sip-bot repo root)
FFI=.venv/lib/python3.13/site-packages/livekit/rtc/resources/liblivekit_ffi.dylib
NC=.venv/lib/python3.13/site-packages/livekit/plugins/noise_cancellation/resources/liblivekit_nc_plugin.dylib

# Local builds
FFI_NEW=$WORKSPACE/rust-sdks/target/release/liblivekit_ffi.dylib
NC_NEW=$WORKSPACE/krisp-noise-filter/packages/rust/target/release/liblivekit_nc_plugin.dylib

# Back up the shipped dylibs once
[ -f "$FFI.orig" ] || cp "$FFI" "$FFI.orig"
[ -f "$NC.orig"  ] || cp "$NC"  "$NC.orig"

# Load project creds for lk + the agent
set -a; source .env.local; set +a
```

Build the dylibs before running any of the variants below:

```bash
(cd "$WORKSPACE/rust-sdks" && cargo build --release -p livekit-ffi)
(cd "$WORKSPACE/krisp-noise-filter/packages/rust" && cargo build --release -p krisp-ffi-plugin)
```

### Swap dylibs for the run you want

```bash
# shipped FFI + new plugin
cp "$FFI.orig" "$FFI" && cp "$NC_NEW"  "$NC"

# new FFI + new plugin
cp "$FFI_NEW"  "$FFI" && cp "$NC_NEW"  "$NC"

# new FFI + shipped plugin
cp "$FFI_NEW"  "$FFI" && cp "$NC.orig" "$NC"
```

### Option A — Automated with `lk load-test` (synthetic publisher)

Agent joins a named room; `lk load-test` publishes a synthetic audio track
into the same room. Good for quickly confirming the filter dispatch path.

```bash
pkill -9 -f "agent.py connect" 2>/dev/null; sleep 2
ROOM=test-room-auto
rm -f /tmp/run.log
nohup uv run python agent.py connect --room "$ROOM" > /tmp/run.log 2>&1 &
until grep -q "input stream attached" /tmp/run.log; do sleep 2; done

lk load-test \
  --url "$LIVEKIT_URL" --api-key "$LIVEKIT_API_KEY" --api-secret "$LIVEKIT_API_SECRET" \
  --room "$ROOM" --audio-publishers 1 --duration 15s

grep -iE "krisp|rust-sdks" /tmp/run.log
```

### Option B — Manual with your mic via LiveKit Meet

Agent joins a named room; you join the same room from your browser via
`meet.livekit.io` with mic enabled. Good for listening to NC quality directly.

```bash
pkill -9 -f "agent.py connect" 2>/dev/null; sleep 2
ROOM=test-room-live
rm -f /tmp/run.log
nohup uv run python agent.py connect --room "$ROOM" > /tmp/run.log 2>&1 &
until grep -q "input stream attached" /tmp/run.log; do sleep 2; done

TOKEN=$(lk token create --identity me --room "$ROOM" --join --valid-for 1h 2>&1 \
        | awk '/^Access token:/ {print $3}')
ENCODED_URL=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "$LIVEKIT_URL")
open "https://meet.livekit.io/custom?liveKitUrl=$ENCODED_URL&token=$TOKEN"

# In another terminal, tail the log while you speak:
tail -f /tmp/run.log | grep -iE "krisp|rust-sdks"
```

### Cleanup

```bash
pkill -9 -f "agent.py connect"
cp "$FFI.orig" "$FFI"
cp "$NC.orig"  "$NC"
```

### Observed results

Tested with temporary `eprintln!` logs added on the two PR branches
([rust-sdks #1019](https://github.com/livekit/rust-sdks/pull/1019),
[krisp-noise-filter #174](https://github.com/livekit/krisp-noise-filter/pull/174))
to make the dispatch path visible at runtime:

- rust-sdks `livekit/src/plugin.rs::new_session` — prints
  `[rust-sdks] audio_filter v2 dispatch: {in}->{out} Hz` or
  `[rust-sdks] audio_filter v1 dispatch: {rate} Hz` depending on which branch
  is taken.
- krisp `audio_filter_create` / `audio_filter_create_v2` — prints
  `[krisp-plugin] audio_filter_create (v1): {rate} Hz` and/or
  `[krisp-plugin] audio_filter_create_v2: {in}->{out} Hz`.

Run via Option A above on macOS arm64, Opus publishers at 48 kHz, agent
configured for 24 kHz output (the `livekit-agents` default).

| Scenario | `$FFI` | `$NC` | Observed stderr | Verdict |
|----------|--------|-------|-----------------|---------|
| Old SDK + new plugin (backwards-compat) | shipped (v1) | new (#174) | `[krisp-plugin] audio_filter_create (v1): 24000 Hz` → `[krisp-plugin] audio_filter_create_v2: 24000->24000 Hz` | Old SDKs keep working with the new plugin. The v1 entrypoint correctly delegates to v2 with equal rates. |
| New SDK + new plugin (v2 fast path) | new (#1019) | new (#174) | `[rust-sdks] audio_filter v2 dispatch: 48000->24000 Hz` → `[krisp-plugin] audio_filter_create_v2: 48000->24000 Hz` | v2 probe + dispatch fires; plugin v2 entrypoint receives asymmetric rates; WebRTC sink is at 48 kHz (passthrough), filter does 48→model_rate→24. |
| New SDK + old plugin (v1 fallback) | new (#1019) | shipped (v1 only) | `[rust-sdks] audio_filter v1 dispatch: 24000 Hz` | v2-capable SDK falls back cleanly when the plugin has no `_v2` symbols. No regression for v1-only plugins (ai-coustics etc.). |

The eprintlns are development-only — revert them before merging either PR.
