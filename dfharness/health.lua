--@ module=true
--luacheck: globals factory
local function build(...)
-- Explicit unit-health watches. Bounded native reads; no affiliation inference.
local h=...
local M={}
function M.condition(unit)
    local out={available=true}
    local function read(field,fn)
        local ok,value=pcall(fn)
        if ok then
            local boolean=field=='alive' or field=='dead' or field=='prone' or field=='conscious'
            if (boolean and type(value)~='boolean') or (not boolean and
                (type(value)~='number' or value<0 or value~=math.floor(value))) then
                ok=false;value='Native condition field has an invalid type or value'
            end
        end
        if ok and value~=nil then out[field]=value
        else
            out.unavailable=out.unavailable or {}
            out.unavailable[field]=ok and 'Native value is absent' or tostring(value):sub(1,180)
        end
    end
    read('alive',function()return dfhack.units.isAlive(unit)end)
    read('dead',function()return dfhack.units.isDead(unit)end)
    read('prone',function()return unit.flags1.on_ground end)
    read('conscious',function()
        local value=unit.counters.unconscious
        assert(type(value)=='number' and value>=0,'Native unconsciousness counter is unavailable')
        assert(type(out.dead)=='boolean','Native death state is unavailable')
        return not out.dead and value==0
    end)
    for _,field in ipairs({'blood_count','blood_max'})do read(field,function()return unit.body[field]end)end
    read('wounds',function()return #unit.body.wounds end)
    read('pain',function()return unit.counters.pain end)
    read('exhaustion',function()return unit.counters2.exhaustion end)
    out.complete=out.unavailable==nil
    return out
end
local function integer(v)
    assert(type(v)=='number' and v==math.floor(v) and v>=0 and v<=2147483647,
        'Native health value is not a nonnegative integer')
    return v
end
local function sample(id,loaded)
    local out={unit_id=id,available=false}
    if not loaded then out.reason='Local map is not loaded';return out end
    local ok,unit=pcall(function()
        local u=df.unit.find(id)
        if u and dfhack.units.isVisible(u) and not dfhack.units.isHidden(u) then return u end
    end)
    if not ok or not unit then
        out.reason=ok and 'Unit is not currently loaded and visible' or tostring(unit):sub(1,180)
        return out
    end
    out.available=true
    local function read(field,fn)
        local success,value=pcall(fn)
        if success then out[field]=value
        else
            out.unavailable=out.unavailable or {}
            out.unavailable[field]=tostring(value):sub(1,180)
        end
    end
    read('blood_count',function()return integer(unit.body.blood_count)end)
    read('wound_ids',function()
        local wounds=unit.body.wounds
        local count=integer(#wounds)
        out.wounds=count
        assert(count<=1024,'Native wound enumeration exceeds 1024 entries')
        local ids,seen=h.array(),{}
        for i=0,count-1 do
            local wid=integer(wounds[i].id)
            assert(not seen[wid],'Native wound identity is duplicated')
            ids[#ids+1]=wid;seen[wid]=true
        end
        table.sort(ids)
        return ids
    end)
    return out
end
function M.read(ids,loaded)
    assert(type(ids)=='table' and #ids<=32,'watch_units must be an array of at most 32 IDs')
    local out,seen=h.array(),{}
    for i,id in ipairs(ids) do
        integer(id);assert(not seen[id],'watch_units IDs must be distinct')
        out[i]=sample(id,loaded);seen[id]=true
    end
    return out
end
function M.matches(expected,current)
    return type(expected)=='table' and h.same(expected,current)
end
-- Player predicates need only counters, never inventory, names or wound bodies.
function M.player(status,fields)
    local out={id=status.adventurer_id,health={}}
    local ok,u=pcall(function()
        assert(status.mode=='adventure' and status.map_loaded,'Local adventurer is not loaded')
        local unit=dfhack.world.getAdventurer()
        assert(unit and unit.id==status.adventurer_id,'Local adventurer identity is unavailable')
        return unit
    end)
    for _,field in ipairs(fields)do
        local success,value=pcall(function()
            assert(ok,u)
            if field=='blood_count' then return integer(u.body.blood_count) end
            assert(field=='wounds','Unknown player health predicate field')
            return integer(#u.body.wounds)
        end)
        if success then out.health[field]=value
        else
            out.health.unavailable=out.health.unavailable or {}
            out.health.unavailable[field]=tostring(value):sub(1,180)
        end
    end
    return out
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
