"""Read district counts and engine quotes without forcing a discount refresh."""

from civ_mcp.lua._helpers import SENTINEL, _int, _lua_get_city


def build_district_costs_query(city_id: int) -> str:
    return f"""
{_lua_get_city(city_id)}
local player = Players[me]
local config = PlayerConfigurations[me]
local traits = {{}}
for row in GameInfo.CivilizationTraits() do
    if row.CivilizationType == config:GetCivilizationTypeName() then traits[row.TraitType] = true end
end
for row in GameInfo.LeaderTraits() do
    if row.LeaderType == config:GetLeaderTypeName() then traits[row.TraitType] = true end
end
local allowed, replaced, parent = {{}}, {{}}, {{}}
for row in GameInfo.Districts() do
    if not row.TraitType or traits[row.TraitType] then allowed[row.DistrictType] = true end
end
for row in GameInfo.DistrictReplaces() do
    parent[row.CivUniqueDistrictType] = row.ReplacesDistrictType
    if allowed[row.CivUniqueDistrictType] then replaced[row.ReplacesDistrictType] = true end
end
local types, counts, completed, unlocked, cityCount = {{}}, {{}}, 0, 0, 0
for row in GameInfo.Districts() do
    if allowed[row.DistrictType] and not replaced[row.DistrictType]
        and row.CostProgressionModel == "COST_PROGRESSION_NUM_UNDER_AVG_PLUS_TECH" then
        local available = true
        if row.PrereqTech then
            local tech = GameInfo.Technologies[row.PrereqTech]
            available = tech ~= nil and player:GetTechs():HasTech(tech.Index)
        end
        if available and row.PrereqCivic then
            local civic = GameInfo.Civics[row.PrereqCivic]
            available = civic ~= nil and player:GetCulture():HasCivic(civic.Index)
        end
        if available then
            unlocked = unlocked + 1
            types[row.Index] = row
            counts[row.Index] = 0
        end
    end
end
for _, city in player:GetCities():Members() do
    cityCount = cityCount + 1
    for _, district in city:GetDistricts():Members() do
        local ownedRow = GameInfo.Districts[district:GetType()]
        if ownedRow and ownedRow.CostProgressionModel == "COST_PROGRESSION_NUM_UNDER_AVG_PLUS_TECH" then
            if district:IsComplete() then completed = completed + 1 end
            for index, row in pairs(types) do
                if (parent[ownedRow.DistrictType] or ownedRow.DistrictType) == (parent[row.DistrictType] or row.DistrictType) then
                    counts[index] = counts[index] + 1
                end
            end
        end
    end
end
local techCount, civicCount = -1, -1
pcall(function() techCount = player:GetStats():GetNumTechsResearched() end)
pcall(function() civicCount = player:GetStats():GetNumCivicsCompleted() end)
print("META|" .. Game.GetCurrentGameTurn() .. "|" .. pCity:GetID() .. "|" .. techCount .. "|" .. civicCount .. "|" .. cityCount)
print("COUNTS|" .. unlocked .. "|" .. completed)
local queue = pCity:GetBuildQueue()
for index, row in pairs(types) do
    local placed, finished = false, false
    for _, district in pCity:GetDistricts():Members() do
        if district:GetType() == index then placed = true; finished = district:IsComplete() end
    end
    local nativeCost, genericCost = -1, -1
    pcall(function() local n = queue:GetDistrictCost(index); if type(n) == "number" and n >= 0 then nativeCost = n end end)
    pcall(function() local n = queue:GetProductionCost(row.Hash); if type(n) == "number" and n >= 0 then genericCost = n end end)
    local predicted = unlocked > 0 and completed >= unlocked and counts[index] < completed / unlocked
    print("DCOST|" .. row.DistrictType .. "|" .. counts[index] .. "|" .. tostring(predicted)
        .. "|" .. (row.CostProgressionParam1 or 0) .. "|" .. nativeCost .. "|" .. genericCost
        .. "|" .. tostring(placed) .. "|" .. tostring(finished))
end
print("{SENTINEL}")
"""


def parse_district_costs(lines: list[str]) -> dict:
    result = {
        "unlocked_types": None,
        "completed_districts": None,
        "discount_status": "unverified",
        "engine_refresh_status": "unknown",
        "observation": {},
        "note": "Counts are current, not the engine's cached refresh count. Quotes do not confirm a placement discount.",
        "districts": [],
    }
    for line in lines:
        if line.startswith("ERR:"):
            raise ValueError(line)
        fields = line.split("|")
        if fields[0] == "META" and len(fields) == 6:
            result["observation"] = dict(zip(
                ("turn", "city_id", "completed_technologies", "completed_civics", "cities_owned"),
                (_int(value) for value in fields[1:]),
            ))
        elif fields[0] == "COUNTS" and len(fields) == 3:
            result["unlocked_types"] = int(float(fields[1]))
            result["completed_districts"] = int(float(fields[2]))
        elif fields[0] == "DCOST" and len(fields) == 9:
            native, generic = (float(value) if float(value) >= 0 else None for value in fields[5:7])
            preserve = fields[1] == "DISTRICT_PRESERVE"
            result["districts"].append({
                "type": fields[1], "placed_empire_wide": int(float(fields[2])),
                "formula_eligible_after_refresh": fields[3] == "true",
                "rules_discount_percent": float(fields[4]),
                "district_cost_api": native, "production_cost_api": generic,
                "price_status": "unknown" if native is None else "conflicting" if generic is not None and native != generic else "engine_quote",
                "placed_in_city": fields[7] == "true", "complete_in_city": fields[8] == "true",
                "new_placement_quote": native if fields[7] == "false" else None,
                "placed_total_cost": native if fields[7] == "true" else None,
                "cost_source": "CityBuildQueue:GetDistrictCost(district.Index)",
                "exception": "Preserve discount may not apply despite formula eligibility" if preserve else None,
            })
    result["districts"].sort(key=lambda item: item["type"])
    if result["unlocked_types"] is None:
        raise ValueError("District counts unavailable")
    return result
