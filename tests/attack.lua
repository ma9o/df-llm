-- Synthetic native actions; no game inputs, world objects or timers are changed.
local source,events_source=...
local function vector(values)
    local out={};for i,value in ipairs(values) do out[i-1]=value end
    return setmetatable(out,{__len=function()return #values end})
end
local function clone(v)
    if type(v)~='table' then return v end
    local out={};for k,value in pairs(v) do out[k]=clone(value) end;return out
end
local unit={id=1,actions=vector({}),flags1={on_ground=false}}
local target={id=2,body={wounds=vector({})}}
local status={reports=vector({})}
local loaded,supported,tag=true,true,'attack'
local callbacks={}
local env=setmetatable({require=function(name)
    assert(name~='plugins.eventful','Synthetic attack fixture uses the native cursor fallback')
    return require(name)
end,df={unit={find=function(id)return id==2 and target or nil end},
    global={world={status=status}},announcement_type={[1]='MOVED_OUT_OF_RANGE',[2]='COMBAT_STRIKE_DETAILS',
        [3]='COMBAT_DODGE',[4]='COMBAT_JUMP_DODGE_STRIKE',[5]='COMBAT_BLOCK',[6]='COMBAT_PARRY',
        [7]='COMBAT_CHARGE_DEFENDER_KNOCKED_OVER',[8]='COMBAT_CHARGE_DEFENDER_TUMBLES',
        [9]='COMBAT_CHARGE_COLLISION'},
    unit_action_type={Attack=1,attrs=setmetatable({},
    {__index=function()return {tag=tag}end})}},dfhack={
    isWorldLoaded=function()return loaded end,isMapLoaded=function()return loaded end,
    world={getAdventurer=function()return unit end,isAdventureMode=function()return true end},
    units={isVisible=function()return true end,isHidden=function()return false end},
    timeout=function(_,mode,callback)assert(mode=='ticks');callbacks[#callbacks+1]=callback;return #callbacks end,
}},{__index=_ENV})
local m=assert(load(source,'attack-fixture','t',env))({array=function()return {}end,copy=clone,
    report_events=assert(load(events_source,'attack-report-events-fixture','t',env))(),
    bindings={support=function()return {native_hotkey_available=supported}end}})
local menu={kind='combat',mode='AIM_ATTACK',target_unit_id=2,attack_flags={'quick'}}
local option={kind='attack',body_part_id=3,item_id=4,attack_index=0}
local function queued(id)
    return {id=id or 10,type=1,data={attack={target_unit_id=2,attack_item_id=4,
        target_body_part_id=3,attack_body_part_id=8,attack_id=0,timer1=2,timer2=2,
        flags={quick=true,heavy=false,wild=false,precise=false,charge=false}}}}
end
local function start(wounds,reports)
    unit.actions=vector({});callbacks={};unit.flags1.on_ground=false
    target.body.wounds=vector(wounds or {});status.reports=vector(reports or {})
    local e=m.prepare({kind='strike'},menu,option)
    local action=queued();unit.actions=vector({action})
    local receipt={evidence=e};local session={world_epoch='a.1',receipts={input=receipt}}
    m.submitted(e,session,receipt,'input')
    return e,action,session,receipt
end
local function tick()
    local fn=table.remove(callbacks,1);assert(fn,'No observer scheduled');fn()
end
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('inactive action unions are never read',function()
    local expired={id=10,type=-1,data=setmetatable({},{__index=function()error('Expired union read')end})}
    unit.actions=vector({expired});local r=m.state()
    assert(r.available and #r.actions==0)
end)
test('queue identity and countdown verify a nonwounding attack and recovery',function()
    local e,a=start();assert(e.phase=='preparing' and not e.strike_observed)
    a.data.attack.timer1=1;tick();assert(not e.strike_observed)
    a.data.attack.timer1=0;tick();assert(e.strike_observed and e.phase=='recovering')
    a.data.attack.timer2=1;tick()
    unit.actions=vector({});tick()
    assert(e.phase=='finished' and e.recovery_observed and not e.tracking and #callbacks==0)
end)
test('disappearance before the strike is not success',function()
    local e=start();unit.actions=vector({});tick()
    assert(e.phase=='unverified' and not e.strike_observed and not e.recovery_observed)
end)
test('interrupted recovery does not invent an observed countdown',function()
    local e,a=start();a.data.attack.timer1=0;tick();unit.actions=vector({});tick()
    assert(e.phase=='unverified' and e.strike_observed and not e.recovery_observed)
end)
test('native ID reuse and countdown reversal invalidate evidence',function()
    local e,a=start();a.data.attack.target_unit_id=99;tick();assert(e.phase=='unverified')
    e,a=start();a.data.attack.timer1=3;tick();assert(e.phase=='unverified')
end)
test('world replacement and receipt expiry stop callbacks before reading',function()
    local e,_,session=start();session.world_epoch='a.2';loaded=false;tick()
    assert(e.phase=='unverified' and #callbacks==0);loaded=true
    e,_,session=start();session.receipts.input=nil;tick()
    assert(e.phase=='unverified' and #callbacks==0)
end)
test('a callback never silently reports an unavailable reader as complete',function()
    local e=start();tag='wrong';tick();assert(e.phase=='unverified' and e.reason)
    tag='attack';supported=false;assert(not m.state().available);supported=true
end)
test('unexpected attack identity or style is not adopted',function()
    for _,field in ipairs({'target_unit_id','attack_item_id','target_body_part_id','attack_id','style'}) do
        unit.actions=vector({});local e=m.prepare({kind='strike'},menu,option)
        local a=queued();if field=='style' then a.data.attack.flags.quick=false else a.data.attack[field]=77 end
        unit.actions=vector({a});callbacks={}
        m.submitted(e,{world_epoch='a.1'}, {},'input')
        assert(e.phase=='unverified' and #callbacks==0)
    end
end)
test('preexisting attacks, inactive aiming, and zero initial timers block',function()
    unit.actions=vector({queued()});assert(not pcall(m.prepare,{kind='strike'},menu,option))
    unit.actions=vector({});menu.mode='CONFIRM';assert(not pcall(m.prepare,{kind='strike'},menu,option));menu.mode='AIM_ATTACK'
    local e=m.prepare({kind='strike'},menu,option);local a=queued();a.data.attack.timer1=0
    unit.actions=vector({a});m.submitted(e,{world_epoch='a.1'}, {},'input')
    assert(e.phase=='unverified' and not e.strike_observed)
end)
test('observer is bounded when native time does not decrement its action',function()
    local e=start();for _=1,8192 do tick()end
    assert(e.phase=='unverified' and not e.tracking and #callbacks==0 and e.reason:find('8192'))
end)
test('new wound IDs are attributed to the adventurer, not another fighter',function()
    local e,a=start();target.body.wounds=vector({{id=0,attacker_unit_id=1}})
    a.data.attack.timer1=0;tick()
    assert(e.effect.resolution=='wounded' and e.effect.wound_ids[1]==0 and e.strike_observed)
    e,a=start();target.body.wounds=vector({{id=0,attacker_unit_id=99}})
    a.data.attack.timer1=0;tick()
    assert(e.effect.resolution=='processed' and e.effect.damage=='unverified')
end)
test('preexisting wounds and old range reports cannot verify this attack',function()
    local e,a=start({{id=0,attacker_unit_id=1}},{{id=5,type=1}})
    a.data.attack.timer1=0;tick()
    assert(e.effect.resolution=='processed' and e.effect.damage=='unverified')
end)
test('range failure is attributed to the player with labelled report text',function()
    local e,a=start();status.reports=vector({{id=0,type=1,text='Your opponent has moved out of range!'}})
    a.data.attack.timer1=0;tick()
    assert(e.effect.resolution=='out_of_range' and e.effect.report_id==0 and e.effect.source=='report_text')
end)
test('player misses dodges blocks and parries are distinct from incoming attacks',function()
    for _,case in ipairs({
        {3,'You miss the frail ettin!','missed'},
        {4,'You attack the frail ettin but He jumps away!','dodged'},
        {5,'You strike at the dwarf but the shot is blocked with a shield!','blocked'},
        {6,'You strike at the dwarf but the shot is parried with a sword!','parried'},
    }) do
        local e,a=start();status.reports=vector({{id=0,type=case[1],text=case[2]}})
        a.data.attack.timer1=0;tick()
        assert(e.effect.resolution==case[3] and e.effect.source=='report_text' and e.effect.language=='en')
    end
    for _,case in ipairs({{3,'The frail ettin misses you!'},
        {4,'The frail ettin attacks you but You jump away!'},
        {5,'The frail ettin strikes at you but the shot is blocked with a shield!'},
        {6,'The dwarf strikes at you but the shot is parried with a hammer!'},
        {3,'The dwarf misses the ettin!'}, {3,'Vous ratez votre adversaire!'}}) do
        local e,a=start();status.reports=vector({{id=0,type=case[1],text=case[2]}})
        a.data.attack.timer1=0;tick();assert(e.effect.resolution=='processed')
    end
end)
test('player dodges and knockdowns resolve a vanished swing without claiming a strike',function()
    for _,case in ipairs({{4,'The frail ettin attacks you but You scramble away!'},
        {4,'You jump away!'}, {4,'You roll away!'},
        {7,'You are knocked over!'}, {8,'You are knocked over and tumble backward!'},
        {9,'The frail ettin collides with you!'}}) do
        local e=start();status.reports=vector({{id=0,type=case[1],text=case[2]}})
        unit.actions=vector({});tick()
        assert(e.phase=='cancelled' and not e.tracking and not e.strike_observed and not e.recovery_observed)
        assert(e.effect.resolution=='cancelled' and e.effect.cause.report_id==0)
    end
end)
test('native prone transition explains cancellation without needing report language',function()
    local e=start();unit.flags1.on_ground=true;unit.actions=vector({});tick()
    assert(e.phase=='cancelled' and e.effect.cause.source=='native_unit_flags')
    e=start();unit.flags1.on_ground=true;tick();unit.actions=vector({});tick()
    assert(e.phase=='unverified') -- already prone in the preceding sample
end)
test('other actors and old incoming reports do not explain a disappeared attack',function()
    for _,case in ipairs({{4,'You attack the frail ettin but He jumps away!'},
        {7,'The frail ettin is knocked over!'}, {9,'The dwarf collides with the ettin!'}}) do
        local e=start();status.reports=vector({{id=0,type=case[1],text=case[2]}})
        unit.actions=vector({});tick();assert(e.phase=='unverified')
    end
    local e=start(nil,{{id=7,type=7,text='You are knocked over!'}})
    unit.actions=vector({});tick();assert(e.phase=='unverified')
    e=start();status.reports=vector({{id=8,type=4,text='You jump away!'}})
    tick();unit.actions=vector({});tick();assert(e.phase=='unverified')
end)
test('interrupted recovery retains the actual hit or miss and does not invent recovery',function()
    local e,a=start();status.reports=vector({{id=0,type=3,text='You miss the ettin!'}})
    a.data.attack.timer1=0;tick()
    status.reports=vector({{id=0,type=3,text='You miss the ettin!'},
        {id=1,type=4,text='The ettin attacks you but You jump away!'}})
    unit.actions=vector({});tick()
    assert(e.phase=='cancelled' and e.strike_observed and not e.recovery_observed)
    assert(e.effect.resolution=='missed' and e.effect.recovery=='cancelled')
end)
test('effects exclude preparing reports, include delayed reports and reject ambiguity',function()
    local e,a=start();status.reports=vector({{id=0,type=3,text='You miss a dwarf!'}})
    tick();a.data.attack.timer1=0;tick();assert(e.effect.resolution=='processed')
    a.data.attack.timer2=1;tick()
    status.reports=vector({{id=1,type=3,text='You miss the ettin!'}})
    unit.actions=vector({});tick();assert(e.phase=='finished' and e.effect.resolution=='missed')
    e,a=start();status.reports=vector({{id=0,type=3,text='You miss the ettin!'},
        {id=1,type=3,text='You miss the dwarf!'}})
    a.data.attack.timer1=0;tick();assert(e.effect.damage=='unverified' and e.effect.unavailable:find('Multiple'))
end)
test('bounded report overflow cannot classify an arbitrary recent result',function()
    local e,a=start();local many={}
    for i=0,512 do many[#many+1]={id=i,type=3,text='You miss the ettin!'} end
    status.reports=vector(many);a.data.attack.timer1=0;tick()
    assert(e.effect.damage=='unverified' and e.effect.unavailable:find('512'))
end)
test('failed optional effect reads preserve phase proof and unknown damage',function()
    local e,a=start();target.body.wounds=nil;a.data.attack.timer1=0;tick()
    assert(e.strike_observed and e.phase=='recovering')
    assert(e.effect.damage=='unverified' and e.effect.unavailable)
    target.body.wounds=vector({})
end)
test('an unseen target keeps its damage unavailable without reading hidden wounds',function()
    local e,a=start();env.dfhack.units.isVisible=function()return false end
    target.body.wounds=setmetatable({},{__len=function()error('Hidden wounds read')end})
    a.data.attack.timer1=0;tick()
    assert(e.strike_observed and e.effect.unavailable:find('no longer visible'))
    env.dfhack.units.isVisible=function()return true end;target.body.wounds=vector({})
end)
return {passed=#names,tests=names,game_inputs=0}
