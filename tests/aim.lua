-- Aiming reads synthetic active menus only. No input or live world access.
local source,bindings_source=...
local function vector(values,allocated)
    local out={_count=allocated or #values}
    for i,v in ipairs(values) do out[i-1]=v end
    return setmetatable(out,{__len=function(v)return v._count end,
        __index=function(_,k)error('Inactive vector slot read: '..tostring(k))end})
end
local function txt(value)return type(value)=='table' and value.value or value end
local parts=vector({{name_singular={[0]={value='upper body'}}},{name_singular={[0]={value='head'}}}})
local unit={id=9,body={body_plan={body_parts=parts}}}
local attacks=vector({{verb_2nd='punch',name='PUNCH',conflict_check_bp=0},
    {verb_2nd='punch',name='PUNCH',conflict_check_bp=1}})
local player={body={body_plan={attacks=attacks,body_parts=vector({
    {name_singular={[0]={value='right hand'}}},{name_singular={[0]={value='left hand'}}}})}}}
local panel={open=true,mode=3,attack_unit=unit,scroll_position_aim_target=0,scrolling_aim_target=false,
    scroll_position_aim_attack=0,scrolling_aim_attack=false}
local info={target=vector({{target_bp=1,initial_hit_chance_adjustment=0,
    initial_hit_squareness_adjustment=-10,modifier_flags={COUNTS_AS_LETHAL=true}}},80),current_target_number=1}
local keys={};for i=1,20 do keys['OPTION'..i]=i end
local env=setmetatable({df={interface_key=keys,item_type={WEAPON=0,SHIELD=1},
    adventure_interface_attack_mode_type={[3]='AIM_TARGET',[4]='AIM_ATTACK'},
    charge_restrict_type={[0]='NONE'},
    global={game={main_interface={adventure={attack=panel}}},world={attack_chance_info=info}}},
    dfhack={getDFVersion=function()return 'v0.53.16 win64 STEAM'end,
        world={getAdventurer=function()return player end},items={
            getReadableDescription=function(item)return item.description end,
            getSubtypeDef=function()return {attacks=vector({{verb_2nd='bash'}})}end}}},{__index=_ENV})
local h={array=function()return {}end,text=txt}
h.bindings=assert(load(bindings_source,'aim-bindings-fixture','t',env))(h)
local m=assert(load(source,'aim-fixture','t',env))(h)
local function menu(mode)return m.menu({kind='combat',mode=mode,target_unit_id=9,options={}})end
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('only current targets are read from preallocated storage',function()
    local r=menu('AIM_TARGET')
    assert(not r.selection_unavailable and #r.options==1 and r.total==1 and not r.truncated)
    local o=r.options[1]
    assert(o.body_part_id==1 and o.label=='head' and o.hit_chance_adjustment==0)
    assert(o.hit_squareness_adjustment==-10 and o.flags[1]=='COUNTS_AS_LETHAL')
    assert(o.selection.scroll_to==0 and not o.click)
end)
test('invalid counts block without traversing retained pointers',function()
    info.current_target_number=81
    local r=menu('AIM_TARGET')
    assert(r.selection_unavailable and #r.options==0)
    info.current_target_number=-1
    assert(menu('AIM_TARGET').selection_unavailable)
    info.current_target_number=0
    r=menu('AIM_TARGET');assert(not r.selection_unavailable and r.total==0 and #r.options==0)
    info.current_target_number=1
end)
test('inactive aiming modes cannot read their retained state',function()
    panel.mode=0
    assert(not pcall(menu,'AIM_TARGET'))
    panel.mode=3
    assert(not pcall(menu,'AIM_ATTACK'))
end)
test('weapon and natural attacks keep native IDs and adjustments',function()
    local item={id=20,description='copper war hammer',getType=function()return 0 end,getSubtype=function()return 0 end}
    panel.mode=4;panel.aim_attack_flag={quick=true,heavy=false};panel.aim_attack_charge_restrict=0
    panel.custom_combat={aim_mod=vector({
        {attack_item=item,attack_index=0,target_bp=1,hit_chance_adjustment=20,hit_squareness_adjustment=0,flags={}},
        {attack_index=1,target_bp=1,hit_chance_adjustment=0,hit_squareness_adjustment=-5,flags={SMALL_AIM_MINUS=true}},
    })}
    local r=menu('AIM_ATTACK')
    assert(not r.selection_unavailable and #r.options==2 and r.attack_flags[1]=='quick')
    assert(r.options[1].item_id==20 and r.options[1].attack_index==0 and r.options[1].label=='bash with copper war hammer')
    assert(r.options[2].item_id==-1 and r.options[2].attack_index==1 and r.options[2].label=='punch (left hand)')
    assert(r.options[2].required_body_part_id==1)
    assert(h.bindings.selection_key(r,r.options[2])=='OPTION2')
    assert(not r.aim_modifiers)
end)
test('unreadable definitions block all partially read choices',function()
    panel.custom_combat.aim_mod[1].attack_index=30
    local r=menu('AIM_ATTACK')
    assert(r.selection_unavailable and #r.options==1 and not r.options[1].selection)
    panel.custom_combat.aim_mod[1].attack_index=1
end)
test('unsupported builds expose IDs without inferred keys',function()
    env.dfhack.getDFVersion=function()return 'new build'end
    local r=menu('AIM_ATTACK')
    assert(r.selection_unavailable and #r.options==2 and not r.options[2].selection)
end)
return {passed=#names,tests=names,game_inputs=0}
