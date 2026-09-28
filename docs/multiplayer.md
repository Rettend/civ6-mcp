# Multiplayer Tuner memory patch

This experimental patch keeps Civ VI's Tuner listener available when entering
multiplayer. It changes one byte in process memory, leaves the executable file
unchanged, and disappears when Civ exits. Single-player does not need it.
Install the repository using the [quickstart](../README.md#quick-start), then follow
the steps below before connecting your MCP client to a multiplayer match.

## Supported build

- Windows Steam **DX11**, executable `CivilizationVI.exe`.
- Tested game version: **1.0.12.68 (1023995)**.
- Executable SHA-256:
  `e7450823cc8e00468cff7b9d7b97c63140eae38ae1d774ba4efa437556c42d63`.
- 64-bit Python 3.12 (uv can install it). The helper uses only the standard library.

The helper discovers the installation path and loaded module address. It rejects
other executable hashes, unexpected module layouts, and unexpected live
instructions. A matching displayed version number is not enough. DX12, other
storefront builds, macOS, and Linux are unsupported by this patch.

## Apply after each Civ launch

1. Disconnect your `civ6` MCP server and close SDK FireTuner if it is running.
2. Enable **Tuner**, disable **Auto End Turn**, and restart Civ if you changed
   Tuner. Launch with **DirectX 11** and stay at the **main menu**.
3. From this repository's root, check and apply:

   ```powershell
   uv run --no-project --python 3.12 python scripts/civ6_tuner_memory_patch.py --action check
   uv run --no-project --python 3.12 python scripts/civ6_tuner_memory_patch.py --action apply
   ```

   `check` is read-only. `original` means the supported process needs the patch;
   `patched` means it is already present. Applying again verifies the existing
   patch without writing. If multiple DX11 instances are running, append
   `--pid 12345`, replacing the example with the intended process ID.
4. Create or load the multiplayer match with your chosen lobby settings and mods.
5. With the map loaded, confirm that port **4318** belongs to Civ:

   ```powershell
   Get-NetTCPConnection -LocalPort 4318 -State Listen |
     Select-Object LocalAddress, LocalPort, OwningProcess
   Get-Process CivilizationVI | Select-Object Id, ProcessName
   ```

6. Reconnect the existing MCP server. Follow the README's first-turn check:
   verify the intended local player and match, compare state with the UI, then
   test a legal action and turn advancement on a disposable save.

Repeat this procedure for every new Civ process. Changing matches or reconnecting
MCP in the same process does not require reapplying. The helper does not verify
that you are at the main menu; follow the ordering above. It can also be copied
and run on its own using Python's standard library.

## Check or restore

Use the `check` command above to inspect the current state. To restore the original
byte, return to the main menu, disconnect MCP, and run:

```powershell
uv run --no-project --python 3.12 python scripts/civ6_tuner_memory_patch.py --action restore
```

Exiting Civ also discards the patch. Restoring does not retroactively close an
existing Tuner connection; restart Civ for a clean return to unmodified behavior.

## Troubleshooting

- **Only port 4319 is listening:** that is AssetCloud hot-loading, not Tuner.
  Do not point MCP there; this crashed the tested build. Return to the main menu
  and check that 4318 reopens, then apply and re-enter the match. Restart Civ if
  it does not reopen. The patch preserves an existing listener; it cannot recreate
  one that has already closed.
- **Unsupported hash or unexpected instructions:** the helper refuses to write.
  A new build needs separate analysis and validation; do not bypass the checks
  or substitute guessed addresses.
- **Access denied:** run the helper with the same elevation as Civ. Normally both
  run as your regular user.
- **Connection fails with 4318 listening:** confirm its owning process and close
  competing Tuner clients. Use one MCP connection per Civ process.
- **Interrupted action:** query fresh game state before retrying, because the
  action may already have executed.

## What has been tested

On September 18, 2026, with the supported executable and BBG 7.5:

- **LAN host versus AI:** one local player and one AI retained port 4318. MCP
  read the overview, units, cities, map, and research; moved a warrior and settler;
  founded a city; selected research and production; and advanced from turn 1 to
  turns 2 and 3. Apply and restore were also verified at the main menu.
- **Internet host versus AI:** the listener, state reads, movement, city founding,
  research, and production worked. The end-turn call was interrupted before its
  result was recorded, so Internet turn advancement is **not confirmed**.
- **Restart:** the helper found the new process, recognized the original
  instruction, and reapplied and verified the patch.

**Synchronization between two real clients remains untested.** Memory verification
alone does not establish multiplayer gameplay support. Each LLM-controlled player
needs its own game client and local MCP server; patch each supported Civ process
before entering the match. Hosting does not expose Tuner for the other players.
Future two-client validation needs to check that moves appear on both clients,
both players can finish turns without desync, and save/reload and rejoining work.

## Patch details

The callback at module-relative address `0x4F7820` conditionally closes Tuner.
At **RVA `0x4F7838`**, the patch changes `74 0D` (`JE`) to `EB 0D` (`JMP`), taking
the existing stack-cleanup and return path. It does not change the shared
game-mode predicate or make the match single-player.

The helper checks the on-disk hash, module image size, and all 45 callback bytes
in live memory. It resolves the module base, temporarily changes page protection,
writes one opcode byte, flushes the instruction cache, restores protection, and
rereads the function. Restore uses the same checks. Expected bytes are defined in
[`scripts/civ6_tuner_memory_patch.py`](../scripts/civ6_tuner_memory_patch.py).
