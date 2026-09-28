# Read the BBG rules for your game

Use the installed Better Balanced Game files to learn the rules of your match.
An online guide or the latest Workshop release may describe a different version.

## Find the installed mod

The [BBG Workshop page](https://steamcommunity.com/sharedfiles/filedetails/?id=2865001760)
has the current release. Subscribe and enable it in Civ's Additional Content menu
before creating a game; BBG requires Rise and Fall and Gathering Storm.

For a Steam install, look under the Steam library containing Civ VI:

```text
<Steam library>/steamapps/workshop/content/289070/2865001760/
```

On a default Windows install, that is:

```text
C:/Program Files (x86)/Steam/steamapps/workshop/content/289070/2865001760/
```

Steam's **Settings → Storage** lists your library locations. For a manually
installed or pinned release, use its folder under Civ VI's `Mods` directory.
Give your agent that folder's path and access to read it through your harness.

Open `BetterBalancedGame.modinfo` and check its name, version, and mod ID against
the mod enabled for the match. A subscribed mod is not necessarily enabled, and
a Workshop update does not change a game that is already running. Record the
version, other gameplay mods, and lobby options in the opening diary entry.

## Look up the rule you need

- Start with `lang/english.xml` for ability descriptions. Search a leader,
  building, policy, or bonus by name, then follow its `LOC_...` key or game ID.
- Read the matching SQL or XML under `sql/` and `data/` for the actual changes.
  Useful starting points include `sql/Base/Districts.sql`, `sql/XP2/Districts.sql`,
  and the governor files under `sql/XP1/` and `sql/XP2/`.
- Check Lua under `scripts/` and `lua/` for effects applied during play.
  For example, `scripts/bbg_script.lua` handles some city-center settings.
- Follow the file list, conditions, and load order in `.modinfo`. A file may be
  disabled, depend on a lobby option, or be overridden by another active mod.
  BBG changes the base game's rules; a value it does not change still comes from
  the game or another mod.

Use MCP results and the game UI for current costs, legal actions, and placement
bonuses. For example, `get_district_advisor` asks the loaded game for adjacency.
If a description disagrees with those results, trace the active SQL/XML and Lua
rather than assuming the tooltip or a remembered vanilla rule is correct.

For browsing, BBG also has a [rules summary](https://civ6bbg.github.io/) and
[source and versioned releases](https://github.com/CivilizationVIBetterBalancedGame/BetterBalancedGame).
Match the version to your installed files before using them for strategy.
