-- Isolated unit-watch reads, including poisoned hidden/offloaded unit storage.
local source,wire_source=...
local function vector(values,count)
    local out={_count=count or #values}
    for i,v in ipairs(values)do out[i-1]=v end
    return setmetatable(out,{__len=function(v)return v._count end,
        __index=function()error('Uninitialized native wound slot')end})
end
local units={[0]={body={blood_count=0,wounds=vector({{id=4},{id=0}})}},
    [2]={body={blood_count=100,wounds=vector({})}}}
local poison=setmetatable({},{__index=function()error('Hidden unit body read')end})
units[3]={hidden=true,body=poison};units[4]={visible=false,body=poison}
local finds=0
local env=setmetatable({df={unit={find=function(id)finds=finds+1;return units[id]end}},
    dfhack={units={isVisible=function(u)return u.visible~=false end,
        isHidden=function(u)return u.hidden==true end}}},{__index=_ENV})
local wire=assert(load(wire_source))()
local m=assert(load(source,'health-fixture','t',env))({array=function()return require('json.internal'):newArray{}end,
    same=function(a,b)return not next(wire.delta(a,b))end})
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('zero IDs/blood and empty wounds are known; order is canonical',function()
    local r=m.read({0,2},true)
    assert(r[1].unit_id==0 and r[1].available and r[1].blood_count==0 and r[1].wounds==2)
    assert(r[1].wound_ids[1]==0 and r[1].wound_ids[2]==4)
    assert(r[2].available and r[2].wounds==0 and #r[2].wound_ids==0)
    assert(m.matches(wire.clone(r),r))
    units[0].body.wounds=vector({{id=0},{id=4}})
    assert(m.matches(r,m.read({0,2},true)))
end)
test('hidden, absent and offloaded units never expose health',function()
    local r=m.read({3,4,5},true)
    for _,v in ipairs(r)do assert(not v.available and v.reason and not v.blood_count)end
    local prior=finds
    r=m.read({0},false)
    assert(finds==prior and not r[1].available and r[1].reason:find('not loaded',1,true))
end)
test('partial failures preserve valid fields without empty wound claims',function()
    units[2].body.wounds=vector({},1025)
    local r=m.read({2},true)[1]
    assert(r.available and r.blood_count==100 and r.wounds==1025)
    assert(not r.wound_ids and r.unavailable.wound_ids)
    units[2].body.wounds=vector({{id=0},{id=0}})
    assert(m.read({2},true)[1].unavailable.wound_ids)
    units[2].body.wounds=vector({});units[2].body.blood_count='0'
    r=m.read({2},true)[1]
    assert(r.unavailable.blood_count and not r.blood_count and #r.wound_ids==0)
    units[2].body.blood_count=100
end)
test('input guard rejects changed health or missing expected samples',function()
    local before=m.read({0,2},true)
    units[0].body.wounds=vector({{id=0},{id=5}})
    assert(not m.matches(before,m.read({0,2},true)))
    units[0].body.wounds=vector({{id=0},{id=4}})
    units[2].body.blood_count=99
    assert(not m.matches(before,m.read({0,2},true)))
    assert(not m.matches(nil,before))
end)
test('unit watch IDs are bounded, distinct native integers',function()
    for _,ids in ipairs({{-1},{false},{1.5},{2147483648},{0,0}})do assert(not pcall(m.read,ids,true))end
    local ids={};for i=1,33 do ids[i]=i end
    assert(not pcall(m.read,ids,true))
    assert(#m.read({},true)==0)
end)
test('target condition preserves zero, false and native death without expanding wounds',function()
    env.dfhack.units.isAlive=function(u)return u.alive end
    env.dfhack.units.isDead=function(u)return u.dead end
    local u={alive=false,dead=true,flags1={on_ground=false},body={blood_count=0,blood_max=100,wounds=vector({})},
        counters={unconscious=0,pain=0},counters2={exhaustion=0}}
    local r=m.condition(u)
    assert(r.available and r.complete and r.alive==false and r.prone==false and r.conscious==false)
    assert(r.blood_count==0 and r.wounds==0 and r.exhaustion==0)
    u.alive=true;u.dead=false;assert(m.condition(u).conscious==true)
    u.alive=false;assert(m.condition(u).conscious==true) -- NOT_LIVING is not death.
end)
test('failed condition fields remain unavailable instead of plausible healthy defaults',function()
    local r=m.condition({alive=true,flags1={},body={blood_count='0',blood_max=100},counters={},counters2={}})
    assert(r.available and not r.complete and r.blood_max==100)
    assert(r.blood_count==nil and r.conscious==nil and r.wounds==nil and r.prone==nil)
    assert(r.unavailable.blood_count and r.unavailable.conscious and r.unavailable.wounds)
end)
test('player progress preserves zero without touching inventory or wound identities',function()
    local forbidden=setmetatable({},{__index=function()error('Unrequested player detail read')end})
    local player={id=0,body={blood_count=0,wounds=vector({forbidden})},inventory=forbidden}
    env.dfhack.world={getAdventurer=function()return player end}
    local status={mode='adventure',map_loaded=true,adventurer_id=0}
    local r=m.player(status,{'blood_count','wounds'})
    assert(r.id==0 and r.health.blood_count==0 and r.health.wounds==1 and not r.health.unavailable)
    player.body.wounds=forbidden
    r=m.player(status,{'blood_count'})
    assert(r.health.blood_count==0 and not r.health.wounds and not r.health.unavailable)
end)
test('offloaded, replaced and unreadable player health stays explicitly unknown',function()
    local calls=0
    env.dfhack.world={getAdventurer=function()calls=calls+1;return {id=2,body={blood_count=false}} end}
    local r=m.player({mode='adventure',map_loaded=false,adventurer_id=0},{'blood_count'})
    assert(calls==0 and r.health.unavailable.blood_count and not r.health.blood_count)
    r=m.player({mode='adventure',map_loaded=true,adventurer_id=0},{'blood_count'})
    assert(calls==1 and r.health.unavailable.blood_count and not r.health.blood_count)
    r=m.player({mode='adventure',map_loaded=true,adventurer_id=2},{'blood_count','wounds'})
    assert(r.health.unavailable.blood_count and r.health.unavailable.wounds and not r.health.wounds)
end)
return {passed=#names,tests=names,game_inputs=0}
