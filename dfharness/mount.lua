--@ module=true
--luacheck: globals factory
local function build(h)
-- Mount, dismount, claim and lead commands through DF's own movement option
-- handlers (adventure_movement_mountst and its siblings), realized like the
-- path command. DF decides adjacency, ownership, refusals and effects; results
-- are read from unit flags and relationships and never written.
local M={}
local CLASSES={mount='adventure_movement_mountst',dismount='adventure_movement_dismountst',
    claim_pet='adventure_movement_claim_petst',lead_animal='adventure_movement_lead_animalst',
    stop_leading='adventure_movement_stop_lead_animalst'}
local function integer(v,lo,hi,label)
    assert(type(v)=='number' and v%1==0 and v>=lo and v<=hi,'Invalid '..label)
    return v
end
local function pos(p)return {x=p.x,y=p.y,z=p.z}end
local function relation(u,name)
    local index=df.unit_relationship_type[name]
    assert(type(index)=='number','Native relationship '..name..' is unavailable')
    return u.relationship_ids[index]
end
local function mount_capable(u)
    local raw=df.creature_raw.find(u.race)
    local caste=raw and raw.caste[u.caste]
    assert(caste,'Native caste is unavailable')
    return caste.flags.MOUNT or caste.flags.MOUNT_EXOTIC
end
function M.animal(u,me)
    local out={id=u.id,name=h.text(dfhack.units.getReadableName(u)),position=pos(u.pos),
        alive=not dfhack.units.isDead(u),
        visible=dfhack.units.isVisible(u) and not dfhack.units.isHidden(u),
        tame=dfhack.units.isTame(u),pet=dfhack.units.isPet(u),mount_capable=mount_capable(u),
        ridden=u.flags1.ridden,owner_id=relation(u,'PetOwner')}
    if me then
        out.adjacent=u.pos.z==me.pos.z
            and math.max(math.abs(u.pos.x-me.pos.x),math.abs(u.pos.y-me.pos.y))<=1
    end
    return out
end
function M.state(ref)
    local ok,out=pcall(function()
        local me=assert(dfhack.world.getAdventurer(),'Local adventurer is unavailable')
        local unit_id=ref
        if type(ref)=='table' then
            -- A figure reference resolves to today's unit ID; an unloaded figure
            -- reads as an absent animal rather than an error.
            local hf=df.historical_figure.find(integer(ref.figure_id,0,2147483647,'figure ID'))
            unit_id=hf and hf.unit_id>=0 and hf.unit_id or -1
        end
        local state={available=true,adventurer_id=me.id,position=pos(me.pos),rider=me.flags1.rider,
            mount_id=relation(me,'RiderMount'),leading_id=relation(me,'Draggee'),queued=h.array()}
        -- A realized option becomes a unit action that runs on the next game
        -- turn; report it so the verifier waits instead of resending.
        for _,a in ipairs(me.actions) do
            state.queued[#state.queued+1]=df.unit_action_type[a.type] or tostring(a.type)
        end
        if unit_id~=nil then
            local u=df.unit.find(integer(unit_id,0,2147483647,'animal unit ID'))
            state.animal=u and M.animal(u,me) or {id=unit_id,present=false}
        end
        return state
    end)
    return ok and out or {available=false,reason=tostring(out):sub(1,240)}
end
function M.companions()
    -- The adventurer's pets and current mount: stable figure IDs beside the
    -- current unit IDs, so a reload never loses the party.
    local out={available=false,companions=h.array()}
    local ok,err=pcall(function()
        local me=assert(dfhack.world.getAdventurer(),'Local adventurer is unavailable')
        local owner=df.unit_relationship_type.PetOwner
        assert(type(owner)=='number','Native pet-owner relationship is unavailable')
        local mount_id=relation(me,'RiderMount')
        local n=0
        for _,u in ipairs(df.global.world.units.active) do
            n=n+1;assert(n<=32768,'Active units exceed the reading bound')
            if u.id~=me.id and not dfhack.units.isDead(u) and (u.relationship_ids[owner]==me.id or u.id==mount_id) then
                local a=M.animal(u,me)
                a.figure_id=u.hist_figure_id>=0 and u.hist_figure_id or nil
                a.mount=u.id==mount_id
                a.cargo_count=#u.inventory
                out.companions[#out.companions+1]=a
            end
        end
        out.rider=me.flags1.rider;out.mount_id=mount_id;out.available=true
    end)
    if not ok then out.reason=tostring(err):sub(1,240) end
    return out
end
function M.validate(action)
    local class=CLASSES[action.command]
    assert(class,'Unknown mount command')
    assert(type(df[class])=='table' and type(df[class].new)=='function','Native '..class..' is unavailable')
    local me=assert(dfhack.world.getAdventurer(),'Local adventurer is unavailable')
    local animal
    if action.command~='dismount' then
        animal=df.unit.find(integer(action.unit_id,0,2147483647,'animal unit ID'))
        assert(animal,'The animal is not loaded')
        local info=M.animal(animal,me)
        assert(info.visible,'The animal is not visible')
        assert(info.alive,'The animal is dead')
        assert(info.adjacent,'The animal is not adjacent')
        if action.command=='mount' then
            assert(info.mount_capable,'This creature is not a mount')
            assert(not me.flags1.rider,'The adventurer is already riding')
        end
    else
        assert(me.flags1.rider,'The adventurer is not riding')
    end
    return me,animal,class
end
function M.submit(action)
    local me,animal,class=M.validate(action)
    local command=df[class]:new()
    local ok,err=pcall(function()
        command.source:assign(me.pos)
        command.dest:assign(animal and animal.pos or me.pos)
        if animal then command.animal=animal end
        if action.command=='mount' then
            assert(type(df.rider_positions_type.STANDARD)=='number','Native rider position is unavailable')
            command.riderposition=df.rider_positions_type.STANDARD
        end
        assert(command:hasRealize(),'The native '..action.command..' command cannot be realized here')
        command:doRealize()
    end)
    command:delete()
    if not ok then error(err,0) end
    return {adapter='native_movement_option',command=action.command,animal_id=animal and animal.id}
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
