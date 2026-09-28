"""Execute generated Lua with hidden-state traps, without connecting to Civ."""

import asyncio

import pytest
from lupa import LuaRuntime

from civ_mcp.game_state import GameState
from civ_mcp.lua._helpers import _LUA_RES_VISIBLE
from civ_mcp.lua.cities import build_city_attack
from civ_mcp.lua.map import (
    build_district_advisor_query,
    build_map_area_query,
    build_wonder_advisor_query,
    parse_district_advisor_response,
)
from civ_mcp.lua.units import (
    build_attack_followup_query,
    build_attack_unit,
    build_builder_tasks_query,
    build_combat_estimate_query,
)
from civ_mcp.narrate import narrate_district_advisor


BASE = """
Game = {GetLocalPlayer=function() return 0 end, GetCurrentGameTurn=function() return 12 end}
GameConfiguration = {GetValue=function() return 123 end}
Locale = {Lookup=function(value) return value end}
revealed, visible, resourceVisible, resourceIndex = true, true, false, 1
PlayersVisibility = {[0]={
    IsRevealed=function() return revealed end,
    IsVisible=function() return visible end,
}}
local resources = {IsResourceVisible=function() return resourceVisible end}
local techs = {HasTech=function() return false end}
local culture = {HasCivic=function() return false end}
local city = {GetX=function() return 0 end, GetY=function() return 0 end,
    GetID=function() return 7 end, GetName=function() return 'Home' end}
local function members(values)
    return {Members=function() return ipairs(values) end}
end
Players = {[0]={GetResources=function() return resources end,
    GetTechs=function() return techs end, GetCulture=function() return culture end,
    GetCities=function() return members({city}) end,
    GetUnits=function() return members({}) end}}
GameInfo = {Resources={[1]={Index=1, ResourceType='RESOURCE_IRON',
    ResourceClassType='RESOURCECLASS_STRATEGIC', PrereqTech='TECH_BRONZE_WORKING'}},
    Technologies={TECH_BRONZE_WORKING={Index=1}}, Civics={}, Units={},
    Improvements={IMPROVEMENT_MINE={ImprovementType='IMPROVEMENT_MINE'}},
    Terrains={[0]={TerrainType='TERRAIN_GRASS_HILLS', Name='Grass Hills'}}, Features={}}
plot = {
    GetX=function() return 0 end, GetY=function() return 0 end, GetIndex=function() return 10 end,
    GetOwner=function() return 0 end, IsWater=function() return false end,
    IsMountain=function() return false end, IsHills=function() return true end,
    GetDistrictType=function() return -1 end, GetImprovementType=function() return -1 end,
    GetResourceType=function() return resourceIndex end,
    GetFeatureType=function() return -1 end, GetTerrainType=function() return 0 end,
    IsRiver=function() return false end, IsCoastalLand=function() return false end,
}
Map = {GetPlot=function(x,y) if x==0 and y==0 then return plot end end,
    GetPlotByIndex=function() return plot end}
CityManager = {GetCity=function() return city end,
    GetOperationTargets=function() return {plots={10}} end}
CityOperationTypes = {BUILD=1, PARAM_BUILDING_TYPE=2, PARAM_DISTRICT_TYPE=3}
city.GetBuildQueue=function() return {CanProduce=function() return true end} end
UnitManager = {GetUnit=function() return {} end}
"""


def lua_run(code, setup=""):
    runtime = LuaRuntime(unpack_returned_tuples=True)
    output = []
    runtime.globals().print = lambda *values: output.append("\t".join(map(str, values)))
    runtime.execute(BASE + setup)
    runtime.execute(code)
    return output


def test_hidden_resource_and_empty_tile_have_identical_builder_tasks():
    query = build_builder_tasks_query()
    hidden = lua_run(query)
    empty = lua_run(query, "resourceIndex=-1")
    assert hidden == empty
    assert any("MINE" in line for line in hidden)
    assert not any("IRON" in line for line in hidden)
    revealed = lua_run(query, "resourceVisible=true")
    assert any("TASK|urgent|" in line and "IRON" in line for line in revealed)


def test_resource_filter_requires_exploration_and_respects_engine_visibility():
    code = _LUA_RES_VISIBLE + "\nprint(visibleResourceType(plot))"
    assert lua_run(code) == ["-1"]
    assert lua_run(code, "resourceVisible=true") == ["1"]
    assert lua_run(code, "resourceVisible=true; revealed=false") == ["-1"]


def test_gamecore_resource_fallback_checks_technology_and_civic():
    setup = """
Players[0].GetResources=function() error('UI API unavailable') end
GameInfo.Resources[1].PrereqCivic='CIVIC_TEST'
GameInfo.Civics.CIVIC_TEST={Index=2}
Players[0].GetTechs=function() return {HasTech=function() return true end} end
"""
    code = _LUA_RES_VISIBLE + "\nprint(visibleResourceType(plot))"
    assert lua_run(code, setup) == ["-1"]
    assert lua_run(code, setup + "Players[0].GetCulture=function() return {HasCivic=function() return true end} end") == ["1"]


def test_hidden_resource_does_not_change_wonder_score():
    setup = "GameInfo.Buildings={BUILDING_TEST={Hash=5, IsWonder=true}}"
    query = build_wonder_advisor_query(7, "BUILDING_TEST")
    assert lua_run(query, setup) == lua_run(query, setup + "; resourceIndex=-1")
    assert any("RESOURCE_IRON" in line for line in lua_run(query, setup + "; resourceVisible=true"))


def test_fog_query_does_not_read_hidden_tile_data():
    setup = """
visible=false
local function forbidden() error('hidden-state access') end
plot.GetTerrainType=forbidden; plot.GetResourceType=forbidden
plot.GetOwner=forbidden; plot.GetImprovementType=forbidden
"""
    assert "FOG|0,0" in lua_run(build_map_area_query(0, 0, 0), setup)
    unexplored = lua_run(build_map_area_query(0, 0, 0), setup + "; revealed=false")
    assert not any(line.startswith("FOG|") for line in unexplored)


@pytest.mark.parametrize("query", [
    build_attack_unit(1, 2, 3), build_combat_estimate_query(1, 2, 3),
    build_attack_followup_query(2, 3), build_city_attack(7, 2, 3),
])
def test_hidden_combat_target_is_rejected_before_any_target_lookup(query):
    output = lua_run(query, "visible=false; Map.GetUnitsAt=function() error('hidden unit') end")
    assert output == ["ERR:TARGET_NOT_VISIBLE", "---END---"]


ADJACENCY = """
GameInfo.Districts={DISTRICT_HARBOR={Hash=8, Index=9}}
GameInfo.Yields={YIELD_SCIENCE={Index=3},YIELD_PRODUCTION={Index=1},
    YIELD_GOLD={Index=2},YIELD_FAITH={Index=5},YIELD_CULTURE={Index=4}}
plot.IsWater=function() return true end
plot.GetAdjacencyYield=function(self,player,city,district,yield)
    assert(player==0 and city==7 and district==9)
    return yield==2 and 6 or 0
end
"""


def test_water_district_uses_native_modded_adjacency():
    output = lua_run(build_district_advisor_query(7, "DISTRICT_HARBOR"), ADJACENCY)
    placements = parse_district_advisor_response(output)
    assert len(placements) == 1
    assert placements[0].adjacency == {"gold": 6}
    assert placements[0].total_adjacency == 6


def test_missing_adjacency_api_returns_unknown_not_zero():
    output = lua_run(build_district_advisor_query(7, "DISTRICT_HARBOR"),
                     ADJACENCY + "plot.GetAdjacencyYield=function() error('missing') end")
    placements = parse_district_advisor_response(output)
    assert not placements[0].adjacency_known
    assert "Adj: unknown" in narrate_district_advisor(placements, "DISTRICT_HARBOR")


@pytest.mark.parametrize("reset", ["VIEW|0|1|123", "VIEW|1|13|123", "VIEW|0|13|456", "load"])
def test_fog_uses_last_observation_and_resets_on_context_change(reset):
    class Connection:
        lines = []

        async def execute_read(self, _):
            return self.lines

        execute_write = execute_read

    async def run():
        connection = Connection()
        game = GameState(connection)
        connection.lines = ["VIEW|0|12|123", "0,0|TERRAIN_GRASS|none|none|0|0|0|IMPROVEMENT_FARM|0|WARRIOR|visible|1|2,0,0,0,0,0|none|Home|none|-1|1"]
        await game.get_map_area(0, 0)
        connection.lines = ["VIEW|0|13|123", "FOG|0,0"]
        fog = (await game.get_map_area(0, 0))[0]
        assert fog.improvement == "IMPROVEMENT_FARM"
        assert fog.observed_turn == 12 and fog.units is None
        if reset == "load":
            game._record_save_load("test_save")
            reset_view = "VIEW|0|13|123"
        else:
            reset_view = reset
        connection.lines = [reset_view, "FOG|0,0"]
        assert (await game.get_map_area(0, 0))[0].terrain == "UNKNOWN"

    asyncio.run(run())


def test_arbitrary_lua_is_absent_from_catalog_and_direct_execution_rejected():
    from civ_mcp.server import mcp, run_lua

    async def run():
        assert "run_lua" not in {tool.name for tool in await mcp.list_tools()}
        with pytest.raises(ValueError, match="disabled"):
            await run_lua(None, "print(Map.GetPlotCount())")
        with pytest.raises(ValueError, match="disabled"):
            await GameState(None).execute_lua("print(Map.GetPlotCount())")

    asyncio.run(run())


def test_tool_arguments_cannot_inject_lua_through_identifiers_or_json():
    from civ_mcp.player_server import validate_arguments

    with pytest.raises(ValueError, match="delimiters"):
        validate_arguments("get_district_advisor", {"district_type": 'X"]; print(Map.GetPlotCount()); --'})
    with pytest.raises(ValueError, match="assignments"):
        validate_arguments("set_policies", {"assignments": '0=X"]; print(1); --'})
    with pytest.raises(ValueError, match="delimiters"):
        validate_arguments("queue_wc_votes", {"votes": '[{"hash":"X\\\"]; print(1); --"}]'})
    validate_arguments("set_policies", {"assignments": '0=POLICY_URBAN_PLANNING, 1=POLICY_AGOGE'})
    validate_arguments("queue_wc_votes", {"votes": '[{"hash":12,"option":1,"target":0,"votes":2}]'})
    validate_arguments("end_turn", {"tactical": 'I moved the Scout. "Continue west" is the next plan.'})


def test_district_cost_queries_keep_conflicting_or_missing_costs_unverified():
    from civ_mcp.lua.district_costs import parse_district_costs

    data = parse_district_costs([
        "COUNTS|3.0|3.0",
        "DCOST|DISTRICT_CAMPUS|0|true|35|28|40|false|false",
        "DCOST|DISTRICT_HOLY_SITE|0|true|35|-1|-1|false|false",
    ])
    assert data["unlocked_types"] == data["completed_districts"] == 3
    assert data["districts"][0]["price_status"] == "conflicting"
    assert data["districts"][1]["district_cost_api"] is None
    assert data["discount_status"] == "unverified"


COST_SETUP = """
local function rows(values)
    local t = {}; for _, row in ipairs(values) do t[row.Index or row.DistrictType] = row end
    return setmetatable(t, {__call=function() local i=0; return function() i=i+1; return values[i] end end})
end
GameInfo.CivilizationTraits=rows({}); GameInfo.LeaderTraits=rows({}); GameInfo.DistrictReplaces=rows({})
local model='COST_PROGRESSION_NUM_UNDER_AVG_PLUS_TECH'
GameInfo.Districts=rows({
    {Index=0,Hash=100,DistrictType='DISTRICT_CAMPUS',RequiresPopulation=true,CostProgressionModel=model,CostProgressionParam1=35},
    {Index=1,Hash=101,DistrictType='DISTRICT_COMMERCIAL_HUB',RequiresPopulation=true,CostProgressionModel=model,CostProgressionParam1=35}})
PlayerConfigurations={[0]={GetCivilizationTypeName=function() return 'CIVILIZATION_PERSIA' end,
    GetLeaderTypeName=function() return 'LEADER_CYRUS' end}}
local function district(index,complete)
    return {GetType=function() return index end, IsComplete=function() return complete end}
end
local all={district(1,true),district(1,true),district(0,false)}
local city=CityManager.GetCity()
city.GetDistricts=function() return {Members=function() return ipairs(all) end} end
city.GetBuildQueue=function() return {GetDistrictCost=function(_,index) assert(index<2); return 28 end,
    GetProductionCost=function(_,hash) assert(hash>=100); return 40 end} end
"""


def test_district_counts_separate_placed_from_completed_and_use_native_cost_api():
    from civ_mcp.lua.district_costs import build_district_costs_query, parse_district_costs

    result = parse_district_costs(lua_run(build_district_costs_query(7), COST_SETUP))
    assert result["unlocked_types"] == 2
    assert result["completed_districts"] == 2
    campus = result["districts"][0]
    assert campus["placed_empire_wide"] == 1
    assert not campus["formula_eligible_after_refresh"]
    assert campus["placed_in_city"] and not campus["complete_in_city"]
    assert campus["price_status"] == "conflicting"
    assert campus["placed_total_cost"] == 28
    assert campus["new_placement_quote"] is None


@pytest.mark.parametrize("completed,placed,unlocked,eligible", [
    (1, 0, 2, False), (2, 0, 2, True), (2, 1, 2, False),
    (3, 1, 2, True), (3, 2, 2, False), (2, 0, 3, False),
])
def test_discount_windows_do_not_promote_a_stale_quote_to_confirmation(completed, placed, unlocked, eligible):
    from civ_mcp.lua.district_costs import build_district_costs_query, parse_district_costs

    setup = COST_SETUP + f"""
all = {{}}
for i=1,{completed} do table.insert(all,district(1,true)) end
for i=1,{placed} do table.insert(all,district(0,false)) end
if {unlocked} == 3 then
    GameInfo.Districts=rows({{GameInfo.Districts[0],GameInfo.Districts[1],
        {{Index=2,Hash=102,DistrictType='DISTRICT_GOVERNMENT',CostProgressionModel=model,CostProgressionParam1=20}}}})
end
"""
    result = parse_district_costs(lua_run(build_district_costs_query(7), setup))
    campus = result["districts"][0]
    assert result["completed_districts"] == completed
    assert result["unlocked_types"] == unlocked
    assert campus["formula_eligible_after_refresh"] is eligible
    assert campus["district_cost_api"] == 28  # Deliberately stale across every state.
    assert result["discount_status"] == "unverified"
    assert result["engine_refresh_status"] == "unknown"


def test_failed_native_district_cost_is_unknown_even_if_generic_quote_succeeds():
    from civ_mcp.lua.district_costs import build_district_costs_query, parse_district_costs

    setup = COST_SETUP + """
city.GetBuildQueue=function() return {
    GetDistrictCost=function() error('API unavailable') end,
    GetProductionCost=function() return 54 end} end
"""
    result = parse_district_costs(lua_run(build_district_costs_query(7), setup))
    assert result["districts"][0]["price_status"] == "unknown"
    assert result["districts"][0]["placed_total_cost"] is None
    assert result["districts"][0]["production_cost_api"] == 54


def test_hidden_move_destination_is_not_inspected_or_given_an_attack_modifier():
    from civ_mcp.lua.units import build_move_unit

    setup = """
visible=false
local unit={GetMovesRemaining=function() return 2 end, GetType=function() return 0 end,
    GetX=function() return 0 end,GetY=function() return 0 end}
GameInfo.Units[0]={FormationClass='FORMATION_CLASS_LAND_COMBAT'}
UnitManager.GetUnit=function() return unit end
UnitOperationTypes={MOVE_TO=1,PARAM_X='x',PARAM_Y='y',PARAM_MODIFIERS='mod'}
UnitManager.CanStartOperation=function() return true end
UnitManager.RequestOperation=function(_,_,params) assert(params.mod==nil) end
Map.GetUnitsAt=function() error('hidden units inspected') end
"""
    assert any(line.startswith("OK:") for line in lua_run(build_move_unit(1, 2, 3), setup))


def test_settlement_lens_uses_only_ui_categories_and_revealed_coordinates():
    from civ_mcp.lua.map import build_settlement_lens_query

    setup = """
visible=false
Players[1]={GetCities=function() error('hidden cities inspected') end}
plot.GetTerrainType=function() error('fog terrain inspected') end
Map.GetContinentPlotsWaterAvailability=function() return {},{},{},{10,11} end
Map.GetContinentPlotsLoyalty=function() return {[10]=-12,[11]=-20} end
"""
    code = build_settlement_lens_query(0, 0, 0)
    assert lua_run(code, setup) == ["LENS|0,0|blocked|-12", "---END---"]
    assert lua_run(code, setup + "; revealed=false") == ["---END---"]
    failed = lua_run(code, setup + "; Map.GetContinentPlotsWaterAvailability=nil")
    assert failed[0].startswith("ERR:LENS_UNAVAILABLE")


def test_settlement_scoring_does_not_inspect_hidden_neighbors_or_cities():
    from civ_mcp.lua.map import build_global_settle_scan

    setup = """
Map.GetGridSize=function() return 1,1 end
Map.GetPlotDistance=function(_,_,x,y) return math.abs(x)+math.abs(y) end
Map.GetContinentPlotsWaterAvailability=function() return {10},{},{},{} end
Map.GetContinentPlotsLoyalty=function() return {} end
Players[1]={GetCities=function() error('hidden cities inspected') end}
plot.GetYield=function() return 1 end
"""
    query = build_global_settle_scan()
    hidden_resource = lua_run(query, setup)
    assert hidden_resource == lua_run(query, setup + "; resourceIndex=-1")
    assert any(line.startswith("SETTLE|") for line in hidden_resource)
    blocked = lua_run(query, setup + "; Map.GetContinentPlotsWaterAvailability=function() return {},{},{},{10} end")
    assert blocked == ["NONE", "---END---"]


@pytest.mark.parametrize("district,yield_name,value", [
    ("DISTRICT_COMMERCIAL_HUB", "gold", 4),
    ("DISTRICT_CAMPUS", "science", 3),
    ("DISTRICT_THEATER", "culture", 6),
    ("DISTRICT_INDUSTRIAL_ZONE", "production", 8),
])
def test_advisor_preserves_the_loaded_preview_instead_of_recomputing_rules(district, yield_name, value):
    setup = ADJACENCY.replace("DISTRICT_HARBOR", district)
    index = {"science": 3, "production": 1, "gold": 2, "culture": 4}[yield_name]
    setup = setup.replace("yield==2 and 6", f"yield=={index} and {value}")
    placements = parse_district_advisor_response(lua_run(build_district_advisor_query(7, district), setup))
    assert placements[0].adjacency == {yield_name: value}


def test_indirect_rival_snapshot_cannot_read_private_state():
    from civ_mcp.lua.overview import build_rival_snapshot_query

    assert lua_run(build_rival_snapshot_query(), "Players=nil; Map=nil") == ["---END---"]


def test_validation_is_enforced_by_actual_mcp_dispatch():
    from civ_mcp.server import mcp

    with pytest.raises(ValueError, match="delimiters"):
        asyncio.run(mcp.call_tool("get_district_advisor", {
            "city_id": 7, "district_type": 'X"]; print(1); --',
        }))


@pytest.mark.parametrize("visibility", ["false", "nil"])
def test_stealth_unit_on_visible_tile_is_not_an_attack_target(visibility):
    setup = f"""
PlayersVisibility[0].IsUnitVisible={"function() return false end" if visibility == "false" else "nil"}
Map.GetPlotDistance=function() return 1 end
local enemy={{GetOwner=function() return 1 end,GetX=function() return 2 end,GetY=function() return 3 end,
    GetType=function() error('stealth unit details inspected') end}}
Map.GetUnitsAt=function() return {{Units=function() local done=false; return function()
    if not done then done=true; return enemy end end end}} end
"""
    assert lua_run(build_city_attack(7, 2, 3), setup) == [
        "ERR:NO_ENEMY|No hostile unit at target tile", "---END---",
    ]


def test_production_menu_never_falls_back_to_static_district_base_cost():
    from civ_mcp.lua.cities import build_city_production_query

    setup = COST_SETUP + """
GameInfo.Districts=rows({{Index=0,Hash=100,DistrictType='DISTRICT_CAMPUS',Cost=54}})
GameInfo.Units=rows({}); GameInfo.Buildings=rows({}); GameInfo.Projects=rows({})
GameInfo.Yields={YIELD_GOLD={Index=2}}
city.GetGold=function() return {} end
city.GetBuildings=function() return {} end
city.GetDistricts=function() return {Members=function() return ipairs({}) end} end
Players[0].GetTrade=function() return {GetOutgoingRouteCapacity=function() return 0 end} end
city.GetBuildQueue=function() return {
    CanProduce=function() return true end,
    GetTurnsLeft=function() error('unavailable') end,
    GetDistrictCost=function() error('unavailable') end} end
"""
    output = lua_run(build_city_production_query(7), setup)
    assert "DISTRICT|DISTRICT_CAMPUS|-1|-1|-1" in output


def test_production_response_retains_before_and_after_cost_observations(monkeypatch):
    import json
    from unittest.mock import AsyncMock
    from civ_mcp import server

    game = AsyncMock()
    game.get_district_costs.side_effect = [
        {"discount_status": "unverified", "completed_districts": 2, "districts": [
            {"type": "DISTRICT_CAMPUS", "new_placement_quote": 28, "placed_total_cost": None}]},
        {"discount_status": "unverified", "completed_districts": 2, "districts": [
            {"type": "DISTRICT_CAMPUS", "new_placement_quote": None, "placed_total_cost": 40}]},
    ]
    game.set_city_production.return_value = "PRODUCING|DISTRICT_CAMPUS"
    monkeypatch.setattr(server, "_get_game", lambda _: game)

    async def logged(ctx, name, params, fn):
        return await fn()

    monkeypatch.setattr(server, "_logged", logged)
    result = asyncio.run(server.set_city_production(None, 7, "DISTRICT", "DISTRICT_CAMPUS", 2, 3))
    observations = json.loads(result.split("(discount unverified):\n", 1)[1])
    assert observations["before"]["district"]["new_placement_quote"] == 28
    assert observations["after"]["district"]["placed_total_cost"] == 40
    assert observations["after"]["discount_status"] == "unverified"
