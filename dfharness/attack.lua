--@ module=true
--luacheck: globals factory
local function build(...)
-- Observe one native aimed attack from submission through strike and recovery.
-- This module never appends actions, changes timers, or sends gameplay input.
local h=...
local M={}
local MAX_ACTIONS,MAX_SAMPLES=256,8192
local identity={'target_unit_id','attack_item_id','target_body_part_id','attack_body_part_id','attack_id'}
local styles={'quick','heavy','wild','precise','charge'}
local function integer(value,name)
    assert(type(value)=='number' and value==math.floor(value),name..' is unavailable')
    return value
end
local function actor()
    assert(dfhack.isWorldLoaded() and dfhack.isMapLoaded() and dfhack.world.isAdventureMode(),
        'No loaded local adventure')
    return assert(dfhack.world.getAdventurer(),'No local adventurer')
end
local function read_actions(unit)
    local out=h.array()
    assert(#unit.actions<=MAX_ACTIONS,'Native action list exceeds '..MAX_ACTIONS)
    local tag=df.unit_action_type.attrs[df.unit_action_type.Attack].tag
    assert(tag=='attack','Native Attack union tag is unsupported')
    for i=0,#unit.actions-1 do
        local action=unit.actions[i]
        -- An expired None action still owns its ID, but not the old attack union.
        if action.type==df.unit_action_type.Attack then
            local data=action.data[tag]
            local entry={id=integer(action.id,'Action ID'),flags={}}
            for _,field in ipairs(identity) do entry[field]=integer(data[field],field) end
            entry.strike_ticks=integer(data.timer1,'Strike timer')
            entry.recovery_ticks=integer(data.timer2,'Recovery timer')
            for _,name in ipairs(styles) do
                assert(type(data.flags[name])=='boolean','Attack flag is unavailable: '..name)
                entry.flags[name]=data.flags[name]
            end
            out[#out+1]=entry
        end
    end
    return out
end
function M.state()
    local ok,out=pcall(function()
        assert(h.bindings.support().native_hotkey_available,'Attack phases are unverified for this build')
        local unit=actor()
        return {available=true,unit_id=unit.id,actions=read_actions(unit)}
    end)
    return ok and out or {available=false,reason=tostring(out):sub(1,240)}
end
local function matches(a,b)
    if a.id~=b.id then return false end
    for _,key in ipairs(identity) do if a[key]~=b[key] then return false end end
    for _,key in ipairs(styles) do if a.flags[key]~=b.flags[key] then return false end end
    return true
end
local function unavailable(evidence,reason)
    evidence.phase='unverified';evidence.reason=reason
    evidence.tracking=false
end
local function effect_baseline(target_id)
    local ok,out=pcall(function()
        local target=assert(df.unit.find(target_id),'Attack target is no longer loaded')
        assert(dfhack.units.isVisible(target) and not dfhack.units.isHidden(target),
            'Attack target is no longer visible')
        local ids=h.array()
        assert(#target.body.wounds<=1024,'Target wound list exceeds 1024')
        for i=0,#target.body.wounds-1 do
            local wound=target.body.wounds[i]
            local id=integer(wound.id,'Wound ID');assert(id>=0,'Wound ID is unavailable')
            ids[#ids+1]={id=id,attacker=integer(wound.attacker_unit_id,'Wound attacker')}
        end
        local reports=df.global.world.status.reports
        return {wounds=ids,report_cursor=#reports>0 and reports[#reports-1].id or -1}
    end)
    return ok and out or {unavailable=tostring(out):sub(1,240)}
end
local function effects(evidence)
    local before=evidence.effect_baseline
    local current=effect_baseline(evidence.target_unit_id)
    local out={resolution='processed',damage='unverified'}
    if before.unavailable or current.unavailable then
        out.unavailable=before.unavailable or current.unavailable;return out
    end
    local wounds=h.array()
    local prior={}
    for _,wound in ipairs(before.wounds) do prior[wound.id]=true end
    for _,wound in ipairs(current.wounds) do
        if not prior[wound.id] and wound.attacker==evidence.unit_id then wounds[#wounds+1]=wound.id end
    end
    table.sort(wounds)
    if #wounds>0 then return {resolution='wounded',wound_ids=wounds} end
    -- On this verified build MOVED_OUT_OF_RANGE is emitted only for the
    -- adventurer's strike attempt (native 0x64a516..0x64a603). Other combat
    -- text has no reliable actor identity, so never parse prose to claim a hit,
    -- miss, block or parry. Unknown damage remains explicit.
    local reports=df.global.world.status.reports
    local inspected=0
    for i=#reports-1,0,-1 do
        local report=reports[i]
        if report.id<=before.report_cursor then break end
        inspected=inspected+1
        if inspected>512 then out.unavailable='Attack report window exceeds 512';break end
        if df.announcement_type[report.type]=='MOVED_OUT_OF_RANGE' then
            return {resolution='out_of_range',report_id=report.id}
        end
    end
    return out
end
function M.prepare(request,menu,option)
    assert(type(request)=='table' and request.kind=='strike','Unknown input evidence request')
    assert(menu and menu.kind=='combat' and menu.mode=='AIM_ATTACK' and option.kind=='attack',
        'Strike evidence requires a native aimed-attack selection')
    local state=M.state()
    assert(state.available,state.reason)
    -- Queueing behind an already pending attack has different timing/target
    -- semantics. Return that fact instead of quietly adopting the older action.
    assert(#state.actions==0,'Another native attack is already pending')
    return {kind='strike',available=true,unit_id=state.unit_id,
        target_unit_id=menu.target_unit_id,body_part_id=option.body_part_id,
        item_id=option.item_id,attack_index=option.attack_index,
        flags=h.copy(menu.attack_flags),phase='submitting',strike_observed=false,
        recovery_observed=false,tracking=false,effect_baseline=effect_baseline(menu.target_unit_id)}
end
function M.sample(evidence)
    local state=M.state()
    if not state.available or state.unit_id~=evidence.unit_id then
        unavailable(evidence,state.reason or 'Adventurer changed during the attack');return false
    end
    local current
    for _,entry in ipairs(state.actions) do if entry.id==evidence.native_action.id then current=entry end end
    if current and not matches(evidence.native_action,current) then
        unavailable(evidence,'Native attack identity changed');return false
    end
    local previous=evidence.latest
    if not current then
        -- A disappearing queue entry alone proves neither a strike nor recovery.
        if evidence.strike_observed and previous.recovery_ticks==1 then
            evidence.phase='finished';evidence.recovery_observed=true;evidence.tracking=false
        else unavailable(evidence,'Native attack disappeared before its phases were verified') end
        return false
    end
    evidence.latest={strike_ticks=current.strike_ticks,recovery_ticks=current.recovery_ticks}
    if current.strike_ticks<0 or current.recovery_ticks<0
        or current.strike_ticks>previous.strike_ticks or current.recovery_ticks>previous.recovery_ticks then
        unavailable(evidence,'Native attack timers changed outside the verified countdown');return false
    end
    if current.strike_ticks==0 then
        -- Verified native processor: time_to_strike decrements to zero, then
        -- attempts this attack (including range/defense failure), then recovers.
        -- This is NOT evidence that a blow landed or that the target was injured.
        if not evidence.strike_observed then
            local ok,effect=pcall(effects,evidence)
            evidence.effect=ok and effect or {resolution='processed',damage='unverified',unavailable=tostring(effect):sub(1,240)}
        end
        evidence.strike_observed=true;evidence.phase='recovering'
    else evidence.phase='preparing' end
    return true
end
function M.submitted(evidence,session,receipt,input_id)
    evidence.world_epoch=session.world_epoch
    local state=M.state()
    if not state.available or state.unit_id~=evidence.unit_id then
        unavailable(evidence,state.reason or 'Adventurer changed during submission');return
    end
    if #state.actions~=1 then
        unavailable(evidence,'Submission did not create exactly one native attack');return
    end
    local action=state.actions[1]
    if action.target_unit_id~=evidence.target_unit_id or action.attack_item_id~=evidence.item_id
        or action.target_body_part_id~=evidence.body_part_id or action.attack_id~=evidence.attack_index then
        unavailable(evidence,'The queued native attack does not match the selected attack');return
    end
    local selected={}
    for _,name in ipairs(evidence.flags) do selected[name]=true end
    for _,name in ipairs(styles) do if action.flags[name]~=(selected[name] or false) then
        unavailable(evidence,'The queued attack style does not match the selection');return
    end end
    evidence.native_action=action
    evidence.latest={strike_ticks=action.strike_ticks,recovery_ticks=action.recovery_ticks}
    if action.strike_ticks<=0 or action.recovery_ticks<=0 then
        unavailable(evidence,'Nonpositive initial attack timers have no verified completion model');return
    end
    evidence.phase='preparing';evidence.tracking=true
    local samples=0
    local function sample()
        if session.world_epoch~=evidence.world_epoch or session.receipts[input_id]~=receipt then
            unavailable(evidence,'World changed or input evidence expired');return
        end
        local ok,again=pcall(M.sample,evidence)
        if not ok then unavailable(evidence,tostring(again):sub(1,240));return end
        if not again then return end
        samples=samples+1
        if samples>=MAX_SAMPLES then unavailable(evidence,'Attack observer reached '..MAX_SAMPLES..' simulation ticks');return end
        if not dfhack.timeout(1,'ticks',sample) then unavailable(evidence,'Native attack observer could not be scheduled') end
    end
    if not dfhack.timeout(1,'ticks',sample) then unavailable(evidence,'Native attack observer could not be scheduled') end
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
