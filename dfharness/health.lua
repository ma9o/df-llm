--@ module=true
--luacheck: globals factory
local function build(...)
-- Explicit unit-health watches. Bounded native reads; no affiliation inference.
local h=...
local M={}
function M.classifications(unit)
    local out={available=true,values={},source='dfhack.units'}
    for _,name in ipairs({'isDanger','isGreatDanger','isOpposedToLife','isAgitated',
        'isWildlife','isTame','isInvader','isUndead','isCrazed'})do
        local ok,value=pcall(function()
            local fn=dfhack.units[name]
            assert(type(fn)=='function','Native predicate is unavailable')
            local result=fn(unit)
            assert(type(result)=='boolean','Native predicate did not return a boolean')
            return result
        end)
        if ok then out.values[name]=value
        else
            out.available=false;out.unavailable=out.unavailable or {}
            out.unavailable[name]=tostring(value):sub(1,180)
        end
    end
    return out
end
function M.creature_flags(unit,names)
    local out={available=true,flags={}}
    local ok,caste=pcall(dfhack.units.getCasteRaw,unit)
    local masks_ok,masks=pcall(function()
        local result={}
        for _,key in ipairs({'uwss_add_caste_flag','uwss_remove_caste_flag'})do
            local flags={}
            for name,value in pairs(unit[key])do
                if type(name)=='string' then
                    assert(type(value)=='boolean','Invalid native creature modifier flag')
                    flags[name]=value
                end
            end
            result[key]=flags
        end
        return result
    end)
    for _,name in ipairs(names or {'NOSTUN','NOPAIN','NOBREATHE','NOEXERT','NOT_LIVING'})do
        local success,value=pcall(function()
            assert(ok and caste,'Native caste is unavailable')
            assert(masks_ok,'Native creature modifier masks are unavailable')
            local base=caste.flags[name]
            assert(type(base)=='boolean','Native creature flag is unavailable')
            -- Not every caste flag has a modifier bit (e.g. DIURNAL). Read
            -- the exposed masks instead of assuming all flag sets are identical.
            local added=masks.uwss_add_caste_flag[name] or false
            local removed=masks.uwss_remove_caste_flag[name] or false
            -- Same precedence as Units.cpp IS_ACTIVE_CASTE_FLAG.
            return not removed and (added or base)
        end)
        if success then out.flags[name]=value
        else
            out.unavailable=out.unavailable or {}
            out.unavailable[name]=tostring(value):sub(1,180)
        end
    end
    out.complete=out.unavailable==nil
    return out
end
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
function M.combat_condition(unit)
    local out=M.condition(unit)
    local function read(name,fn)
        local ok,value=pcall(fn)
        if ok then out[name]=value
        else
            out.unavailable=out.unavailable or {}
            out.unavailable[name]=tostring(value):sub(1,180)
        end
    end
    local function count(value)
        assert(type(value)=='number' and value>=0 and value%1==0,'Invalid native limb count')
        return value
    end
    read('projectile',function()
        local flag=unit.flags1.projectile
        assert(type(flag)=='boolean','Native projectile state is unavailable')
        return flag
    end)
    read('functional_limbs',function()
        local limbs={}
        for _,kind in ipairs({'stand','grasp','fly'})do
            limbs[kind]={count(unit.status2['limbs_'..kind..'_count']),count(unit.status2['limbs_'..kind..'_max'])}
        end
        return limbs
    end)
    read('parts_with_status',function()
        local parts=unit.body.body_plan.body_parts
        local statuses=unit.body.components.body_part_status
        assert(#parts<=512 and #statuses==#parts,'Native anatomy is oversized or inconsistent')
        local result=h.array()
        local total=0
        for id=0,#parts-1 do
            local flags=h.array()
            for name,value in pairs(statuses[id])do
                if type(name)=='string' and value==true then flags[#flags+1]=name end
            end
            if #flags>0 then
                total=total+1
                if #result<16 then
                    table.sort(flags)
                    local name=assert(parts[id].name_singular[0],'Native body-part name is absent')
                    result[#result+1]={id=id,name=h.text(name),flags=flags}
                end
            end
        end
        if total>#result then out.parts_omitted=total-#result end
        return result
    end)
    read('grapples',function()
        local list=unit.status.wrestle_items
        out.grapple_count=count(#list)
        local result=h.array()
        for i=0,math.min(#list,16)-1 do
            local grip=list[i]
            if grip._kind=='primitive' then
                error('DFHack exposes the active grapple count, but its shared-pointer hold records are opaque',0)
            end
            local state=df.wrestle_state_type[grip.state]
            assert(type(state)=='string','Unknown native wrestle state')
            for _,name in ipairs({'unit','self_bp','other_bp','item1','item2','advantage'})do
                local value=grip[name]
                assert(type(value)=='number' and value%1==0,'Invalid native grapple field: '..name)
            end
            result[#result+1]={unit_id=grip.unit,self_body_part_id=grip.self_bp,
                other_body_part_id=grip.other_bp,state=state,advantage=grip.advantage,
                item_id=grip.item1,other_item_id=grip.item2}
        end
        if #list>#result then out.grapples_omitted=#list-#result end
        return result
    end)
    out.complete=out.unavailable==nil and not out.parts_omitted and not out.grapples_omitted
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
