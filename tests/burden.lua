-- Isolated native-shaped units. UI, executable metadata, gait state and
-- container traversal are poisoned: none may be a dependency of burden.
local source=...
local function poison()return setmetatable({},{__index=function()error('Unrequested state accessed')end})end
local function vector(values)
    local out={};for i,v in ipairs(values)do out[i-1]=v end
    return setmetatable(out,{__len=function()return #values end})
end
local flags=function(v)return setmetatable(v or {},{__index=function()return false end})end
local calls={strength=0,skill=0,armor=0}
local fake_df=setmetatable({global={gamemode=df.game_mode.ADVENTURE,debug_turbospeed=false,
    game=poison(),gps=poison()}},{__index=df})
local fake_dfhack={screen=poison(),internal=poison(),units={
    getPhysicalAttrValue=function(u,attribute)
        assert(attribute==df.physical_attribute_type.STRENGTH);calls.strength=calls.strength+1;return u.strength
    end,
    getEffectiveSkill=function(u,skill)
        assert(skill==df.job_skill.ARMOR);calls.skill=calls.skill+1;return u.armor_skill
    end,
    isHidingCurse=function(u)return u.hiding_curse==true end}}
local env=setmetatable({df=fake_df,dfhack=fake_dfhack},{__index=_ENV})
local m=assert(load(source,'burden-fixture','t',env))()
local next_id=0
local function carried(w,f,mode,armor)
    local id=next_id;next_id=next_id+1
    return {mode=df.inv_item_role_type[mode or 'Weapon'],item={id=id,flags={weight_computed=true},
        weight={whole=w,fraction=f or 0},contents=poison(),
        isArmor=function()calls.armor=calls.armor+1;return armor==true end}}
end
local function unit(items)
    return {id=0,strength=1100,armor_skill=1,body={size_info={size_cur=5731},body_plan=poison()},
        flags1=flags(),flags2=flags{calculated_bodyparts=true},flags3=flags(),
        inventory=vector(items or {}),job=poison(),enemy=poison(),counters2={sleepiness_timer=0}}
end
local function close(a,b)assert(math.abs(a-b)<1e-9,tostring(a)..' ~= '..tostring(b))end
local tests={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));tests[#tests+1]=name end

test('live regression reads load and capacity without a HUD or gait dependency',function()
    local r=m.read(unit{carried(95,462250)})
    assert(r.burden.available and r.burden.label=='Overburdened')
    close(r.capacity.weight_kg,63.04);close(r.load_penalty.effective_weight_kg,95.46225)
    assert(r.burden.source=='dfhack_lua_unit_burden' and calls.strength==1 and calls.skill==1)
    close(r.burden.thresholds.overburdened_above_kg,94.56)
end)
test('strict thresholds and odd capacity preserve unburdened and false',function()
    for _,case in ipairs({{0,0,'unburdened'},{63,49999,'unburdened'},
            {63,50000,'burdened'},{94,569999,'burdened'},{94,570000,'overburdened'}})do
        local r=m.read(unit{carried(case[1],case[2])}).burden
        assert(r.available and r.state==case[3])
        if r.state=='unburdened' then assert(r.severity==0 and r.burdened==false and r.overburdened==false)end
    end
    local u=unit{carried(90,19999)};u.body.size_info.size_cur=6001;u.strength=1000
    assert(m.read(u).burden.state=='burdened')
    u.inventory[0].item.weight.fraction=20000
    assert(m.read(u).burden.state=='overburdened')
end)
test('armor discount follows native modes and rounds mass parts separately',function()
    local u=unit{carried(27,307500,'Worn',true),carried(3,500000,'Weapon',true),carried(17,511750,'Worn',false)}
    u.armor_skill=2
    local r=m.read(u).load_penalty
    close(r.effective_weight_kg,42.261593);assert(r.discounted_item_count==1)
    u.armor_skill=1;close(m.read(u).load_penalty.effective_weight_kg,48.31925)
    u=unit{carried(27,307500,'WrappedAround',true)};u.armor_skill=15
    r=m.read(u);assert(r.load_penalty.effective_weight_kg==0 and r.burden.state=='unburdened')
end)
test('containers use the root cache once and every call samples fresh state',function()
    local u=unit{carried(14,511750,'Worn',false)}
    local r=m.read(u);assert(r.load_penalty.root_item_count==1)
    close(r.load_penalty.effective_weight_kg,14.51175)
    u.inventory[0].item.weight.whole=96;assert(m.read(u).burden.overburdened)
    u.strength=2000;assert(m.read(u).burden.state=='unburdened')
end)
test('empty inventory and minimum capacity are known zero',function()
    local u=unit();u.strength=0;u.body.size_info.size_cur=0
    local r=m.read(u)
    assert(r.capacity.weight_kg==0.01 and r.load_penalty.effective_weight_kg==0)
    assert(r.load_penalty.applied==false and r.burden.available and r.burden.capacity_used_percent==0)
end)
test('large body branch and arithmetic bounds are explicit',function()
    close(m.capacity(300999,1100).weight_kg,3300)
    close(m.capacity(299999,1100).weight_kg,3299.98)
    assert(not pcall(m.capacity,2147483647,2147483647))
    local u=unit{carried(2147483647)}
    local r=m.read(u);assert(r.capacity.available and not r.burden.available and r.burden.state==nil)
end)
test('stale weights fail without refreshing the cache or discarding capacity',function()
    local u=unit{carried(98,462250)};u.inventory[0].item.flags.weight_computed=false
    local r=m.read(u)
    assert(r.capacity.available and not r.load_penalty.available and not r.burden.available)
    assert(r.load_penalty.reason:find('weight cache requires refresh',1,true))
    assert(u.inventory[0].item.flags.weight_computed==false and u.inventory[0].item.weight.whole==98)
end)
test('unreadable weights and API failures never become healthy defaults',function()
    local u=unit{carried(98)};u.inventory[0].item.weight.fraction=nil
    assert(not m.read(u).burden.available)
    u=unit();u.strength=nil;assert(not m.read(u).capacity.available)
    u=unit();u.armor_skill=-1;assert(not m.read(u).burden.available)
    u=unit{carried(98,0,'Worn',true)};u.armor_skill=2
    u.inventory[0].item.isArmor=function()error('Native method is missing')end
    assert(not m.read(u).burden.available)
end)
test('duplicate roots and bounded enumeration never report partial totals as complete',function()
    local entry=carried(1);local u=unit{entry,entry}
    assert(not m.read(u).burden.available)
    u.inventory=setmetatable({},{__len=function()return 4097 end,__index=function()error('Bound was ignored')end})
    local r=m.read(u);assert(not r.burden.available and r.load_penalty.reason:find('4096',1,true))
end)
test('offloaded units and unsupported mount or curse state are explicit',function()
    assert(not m.read(nil).burden.available)
    local u=unit();u.flags1.rider=true;assert(not m.read(u).burden.available)
    u.flags1.rider=false;u.uwss_att_change={};u.hiding_curse=true;assert(not m.read(u).burden.available)
    u.hiding_curse=false;u.flags2.calculated_bodyparts=false;assert(not m.read(u).capacity.available)
end)
test('speed exemptions do not invent a burden exemption',function()
    local u=unit{carried(98,462250)};u.flags3.scuttle=true
    local r=m.read(u);assert(r.load_penalty.ignored and not r.load_penalty.applied and r.burden.overburdened)
end)
test('known effective-skill ambiguity is explicit only when armor can be affected',function()
    local u=unit{carried(98,0,'Worn',true)};u.counters2.sleepiness_timer=846000
    local r=m.read(u);assert(r.capacity.available and not r.burden.available)
    assert(r.load_penalty.reason:find('effective armor skill is ambiguous',1,true))
    u.armor_skill=0;assert(m.read(u).burden.available)
    u.armor_skill=1;u.counters2.sleepiness_timer=864000;assert(m.read(u).burden.available)
    u.counters2.sleepiness_timer=846000;u.inventory[0].mode=df.inv_item_role_type.Weapon
    assert(m.read(u).burden.available)
end)
test('coverage preserves unavailable readings through the shared character report',function()
    local out={encumbrance={weight_complete=false},unavailable={}}
    local u=unit{carried(98)};u.inventory[0].item.flags.weight_computed=false
    m.apply(u,out,{unavailable=function(path,reason)out.unavailable[#out.unavailable+1]={path=path,reason=reason}end})
    assert(out.encumbrance.capacity.available and #out.unavailable==2)
    u.inventory[0].item.flags.weight_computed=true
    m.apply(u,out,{unavailable=function()error('Unexpected incomplete result')end})
    assert(out.encumbrance.load_penalty.physical_weight_complete==false)
end)
return {passed=#tests,tests=tests,game_inputs=0}
