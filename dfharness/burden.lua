--@ module=true
--luacheck: globals factory getBurden
-- Read-only DFHack Lua helper. Uses mapped unit/item state and DFHack attribute
-- and skill APIs; never reads the screen, refreshes caches, or advances the game.
local function build()
local M={}
local floor,max=math.floor,math.max
local SOURCE='dfhack_lua_unit_burden'
local MAX_INVENTORY=4096
local function integer(value,low,high,name)
    assert(type(value)=='number' and value==floor(value) and value>=low and value<=high,
        (name or 'Value')..' is missing or outside its supported integer range')
    return value
end
local function i32(value)return integer(value,0,2147483647)end
local function boolean(value,name)
    assert(type(value)=='boolean',(name or 'Flag')..' is unavailable')
    return value
end
local function reading(fn)
    local ok,result=pcall(fn)
    if ok then result.available=true;result.source=SOURCE;return result end
    return {available=false,source=SOURCE,reason=tostring(result):sub(1,240)}
end

-- Keep DF's integer mass units and division order. This is the burden helper's
-- calculation, not a call to the disabled computeMovementSpeed port.
function M.capacity(size,strength)
    i32(size);i32(strength)
    local capacity=size>=300000 and i32(floor(size/1000)*strength) or floor(i32(size*strength)/1000)
    capacity=max(1,capacity)
    return {weight_kg=capacity/100,native_capacity=capacity,size_cur=size,strength=strength,
        meaning='No movement penalty up to this skill-adjusted load; not a hard inventory limit',
        load_quantization_kg=0.01,attribute_source='dfhack.units.getPhysicalAttrValue'}
end

function M.read(unit)
    local result={}
    local valid,why=pcall(function()
        assert(unit,'No loaded unit is available')
        assert(df.global.gamemode==df.game_mode.ADVENTURE,'Burden helper requires Adventure mode')
        assert(boolean(unit.flags2.calculated_bodyparts,'Body cache flag'),'Native body cache requires refresh')
        assert(not boolean(unit.flags1.rider,'Rider flag') and not boolean(unit.flags1.ridden,'Ridden flag'),
            'Mounted burden is not supported')
        assert(not unit.uwss_att_change or not dfhack.units.isHidingCurse(unit),
            'Hidden-curse burden is not supported')
    end)
    local function checked()assert(valid,tostring(why))end
    result.capacity=reading(function()
        checked()
        local strength=dfhack.units.getPhysicalAttrValue(unit,df.physical_attribute_type.STRENGTH)
        return M.capacity(unit.body.size_info.size_cur,strength)
    end)
    result.load_penalty=reading(function()
        checked()
        assert(result.capacity.available,'Carrying capacity is unavailable')
        local inventory=unit.inventory
        integer(#inventory,0,MAX_INVENTORY,'Root inventory count (limit 4096)')
        local skill=i32(dfhack.units.getEffectiveSkill(unit,df.job_skill.ARMOR))
        local worn,wrapped=df.inv_item_role_type.Worn,df.inv_item_role_type.WrappedAround
        assert(type(worn)=='number' and type(wrapped)=='number','Native worn inventory roles are unavailable')
        local whole,fraction,discounted=0,0,0
        local seen={}
        for index=0,#inventory-1 do
            local entry=inventory[index]
            local item=assert(entry.item,'Inventory item is unavailable')
            local id=i32(item.id)
            assert(not seen[id],'Duplicate root inventory item '..id);seen[id]=true
            assert(boolean(item.flags.weight_computed,'Item weight cache flag'),
                'Item '..id..' weight cache requires refresh')
            local w,f=i32(item.weight.whole),integer(item.weight.fraction,0,999999,'Fractional mass')
            integer(entry.mode,0,2147483647,'Inventory role')
            if skill>0 and (entry.mode==worn or entry.mode==wrapped) then
                if boolean(item:isArmor(),'Armor classification') then
                    -- DFHack's effective-skill port quarters at 846000; the
                    -- game's final sleep stage starts at 864000. Integer
                    -- division loses information, so do not invent a correction.
                    local sleep=i32(unit.counters2.sleepiness_timer)
                    assert(sleep<846000 or sleep>=864000,
                        'DFHack effective armor skill is ambiguous at sleep counters 846000-863999')
                    if skill>1 then
                        local factor=max(0,15-skill)
                        w=floor(i32(w*factor)/16);f=floor(i32(f*factor)/16)
                        discounted=discounted+1
                    end
                end
            end
            -- Root item caches already include their contents. Do not traverse
            -- containers or count their children for a second time.
            whole=i32(whole+w);fraction=i32(fraction+f)
            whole=i32(whole+floor(fraction/1000000));fraction=fraction%1000000
        end
        local weight=i32(i32(whole*100)+floor(fraction/10000))
        local capacity=result.capacity.native_capacity
        local excess=max(0,weight-capacity)
        local ignored=boolean(unit.flags3.scuttle,'Scuttle flag')
            or boolean(unit.flags3.ghostly,'Ghost flag')
            or boolean(df.global.debug_turbospeed,'Turbo speed flag')
        local cost=0
        if excess>0 and not ignored then
            cost=excess>=1000000 and i32(floor(excess/capacity)*2000) or floor(i32(excess*2000)/capacity)
            cost=max(1,cost)
        end
        return {armor_skill_effective=skill,skill_source='dfhack.units.getEffectiveSkill',
            discounted_item_count=discounted,root_item_count=#inventory,
            effective_weight_kg=whole+fraction/1000000,native_weight=weight,
            compared_weight_kg=weight/100,excess_weight_kg=excess/100,capacity_used_percent=weight/capacity*100,
            movement_cost_added=cost,applied=cost>0,ignored=ignored,units='native_movement_cost',
            weight_source='native_root_inventory_caches'}
    end)
    result.burden=reading(function()
        assert(result.capacity.available and result.load_penalty.available,
            result.load_penalty.reason or result.capacity.reason or 'Carried load is unavailable')
        local weight,capacity=result.load_penalty.native_weight,result.capacity.native_capacity
        local heavy=floor(i32(capacity*3)/2)
        local severity=weight>heavy and 2 or weight>capacity and 1 or 0
        return {severity=severity,state=({'unburdened','burdened','overburdened'})[severity+1],
            label=({'Unburdened','Burdened','Overburdened'})[severity+1],
            burdened=severity>0,overburdened=severity==2,
            compared_weight_kg=weight/100,capacity_used_percent=weight/capacity*100,
            thresholds={burdened_above_kg=capacity/100,overburdened_above_kg=heavy/100}}
    end)
    return result
end

function M.apply(unit,out,h)
    local result=M.read(unit)
    out.encumbrance=out.encumbrance or {}
    for name,value in pairs(result)do
        out.encumbrance[name]=value
        if not value.available then h.unavailable('encumbrance.'..name,value.reason)end
    end
    if result.load_penalty.available then
        result.load_penalty.physical_weight_complete=out.encumbrance.weight_complete
    end
end
return M
end
-- Also usable directly by DFHack scripts, without the harness bridge.
function getBurden(unit)return build().read(unit)end
if dfhack_flags and dfhack_flags.module then factory=build else return build()end
