-- Synthetic characters run in DFHack's Lua runtime without editing game units.
local reader_source = ...
local function vector(values)
    local result={}
    for i,value in ipairs(values) do result[i-1]=value end
    return setmetatable(result,{__len=function() return #values end})
end
local function zeros(values) return setmetatable(values or {},{__index=function() return 0 end}) end
local function false_flags(values) return setmetatable(values or {},{__index=function() return false end}) end
local function fixture()
    local parts=vector({
        {token='BODY',name_singular=vector({{value='upper body'}}),con_part_id=-1},
        {token='LHAND',name_singular=vector({{value='left hand'}}),con_part_id=0},
    })
    local attrs,mental,traits,gaits={},{},{},{}
    for i=0,5 do attrs[i]={value=1100+i,max_value=2200,soft_demotion=0} end
    for i=0,12 do mental[i]={value=1000+i,max_value=2000,soft_demotion=0} end
    for i=0,49 do traits[i]=50 end
    for i=0,4 do gaits[i]=i==0 and 0 or -1 end
    local emotions={}
    for i=0,101 do
        emotions[#emotions+1]={type=0,thought=0,strength=i,severity=0,relative_strength=1,
            subthought=-1,year=100,year_tick=i,flags={}}
    end
    local layer=zeros{body_part_id=1,layer_idx=0,global_layer_idx=1,bleeding=77,
        flags1={cut=true,diagnosed=false},flags2={}}
    local wound=zeros{id=9,attacker_unit_id=42,attacker_hist_figure_id=-1,syndrome_id=-1,
        parts=vector({layer}),flags={infection=true,sutured=false}}
    local symptom={ticks=12,delay=0,quantity=13,flags={active=true},target_bp=vector({1}),
        target_layer=vector({0}),target_quantity=vector({13}),target_ticks=vector({12}),target_delay=vector({0})}
    local syndrome={type=5,year=100,year_time=20,ticks=12,reinfection_count=0,wound_id=-1,
        flags={},symptoms=vector({symptom})}
    return {
        id=7,name='Fixture',hist_figure_id=10,race=0,caste=0,sex=1,birth_year=75,birth_time=0,
        custom_profession='',civ_id=-1,cultural_identity=0,military={squad_id=-1,squad_position=-1},
        counters=zeros{},counters2=zeros{hunger_timer=999},flags1=false_flags{},
        flags2=false_flags{breathing_good=true},flags3=false_flags{},effective_rate=1000,
        body={blood_count=4500,blood_max=5600,infection_level=0,physical_attrs=attrs,size_info=zeros{},
            body_plan={body_parts=parts,gait_info={[0]=vector({zeros{action_string_idx=0,full_speed=900,flags={}}})}},
            components={body_part_status=vector({{},{missing=true,has_bandage=false}})},wounds=vector({wound})},
        status2=zeros{},syndromes={active=vector({syndrome})},enemy={gait_index=gaits},
        actions=vector({{id=12,type=0}}),
        inventory=vector({}),
        status={command_gait_index=gaits,current_soul={mental_attrs=mental,
            skills=vector({{id=df.job_skill.HAMMER,rating=1,experience=5,rusty=1,natural_skill_lvl=0}}),
            personality={current_focus=75,undistracted_focus=100,stress=500,longterm_stress=0,combat_hardened=0,
                traits=traits,values=vector({{type=0,strength=7}}),
                needs=vector({{id=0,need_level=1,focus_level=-100,deity_id=-1}}),
                dreams=vector({{local_id=0,type=0,flags={}}}),emotions=vector(emotions)}}},
    }
end

local fake_df=setmetatable({
    global={world={raws={creatures={action_strings=vector({{value='Walk'}})}}}},
    syndrome={find=function()
        return {syn_name='fixture pain',syn_identifier='FIXTURE',
            ce=vector({{getType=function() return df.creature_interaction_effect_type.PAIN end}})}
    end},
},{__index=df})
local fake_units={
    getCasteRaw=function() return {caste_id='MALE'} end,
    getAge=function() return 25.5 end,
    getRaceName=function() return 'HUMAN' end,
    getProfessionName=function() return 'Hammerman' end,
    getProfession=function() return df.profession.HAMMERMAN end,
    getKillCount=function() return 0 end,
    getPhysicalAttrValue=function(_,id) return 950+id end,
    getMentalAttrValue=function(_,id) return 800+id end,
    getEffectiveSkill=function() return 0 end,
    getExperience=function() return 505 end,
    getStressCategory=function() return 4 end,
    getGoalName=function() return 'A fixture goal' end,
    isGoalAchieved=function() return false end,
}
local environment=setmetatable({df=fake_df,dfhack={units=fake_units,
    items={getReadableDescription=function(item) return item.description end},
    translation={translateName=function(name) return name end}}},{__index=_G})
local reader=assert(load(reader_source,'character fixture','t',environment))
local function run(unit, sheet, ui, status)
    return reader(unit,sheet or {id=7,name='Fixture',inventory={{id=20,body_part_id=0}}},
        {array=function() return require('json.internal'):newArray{} end,text=function(s) return s or '' end,
         ui=ui,status=status})
end

local results={}
local function test(name,fn)
    fn()
    results[#results+1]=name
end
local function has_unavailable(result,path)
    for _,item in ipairs(result.unavailable) do if item.path==path then return true end end
    return false
end
test('zero_based_anatomy_and_wound_mapping',function()
    local r=run(fixture())
    assert(#r.body.parts==2 and r.body.parts[1].id==0)
    assert(r.inventory[1].body_part_name=='upper body')
    assert(r.body.wounds[1].parts[1].body_part_id==1)
    assert(r.body.wounds[1].parts[1].body_part_name=='left hand')
    assert(r.body.wounds[1].parts[1].bleeding==77)
    assert(r.body.wounds[1].parts[1].flags1[1]=='cut')
    assert(r.body.parts[2].active_status_flags[1]=='missing')
end)
test('false_zero_and_effective_values_survive',function()
    local r=run(fixture())
    assert(r.health.flags.on_ground==false and r.health.unconscious==0)
    assert(r.personality.goals[1].achieved==false)
    assert(r.attributes.physical[1].value==1100 and r.attributes.physical[1].effective==950)
    assert(r.skills[1].rating==1 and r.skills[1].effective==0)
    assert(r.needs.psychological[1].focus_level==-100)
    local encoded=require('json').encode(r,{pretty=false})
    assert(encoded:find('"achieved":false',1,true))
end)
test('syndrome_effect_and_target_mapping',function()
    local r=run(fixture())
    local s=r.body.syndromes[1]
    assert(s.name=='fixture pain' and s.identifier=='FIXTURE')
    assert(s.symptoms[1].type=='PAIN')
    assert(s.symptoms[1].targets[1].body_part_id==1 and s.symptoms[1].targets[1].quantity==13)
end)
test('bounded_emotions_report_truncation',function()
    local r=run(fixture())
    assert(#r.personality.emotions==100 and r.personality.emotions[1].strength==2)
    assert(r.personality.emotions[100].strength==101)
    assert(r.truncated[1].path=='personality.emotions' and r.truncated[1].total==102)
end)
test('missing_soul_does_not_hide_physical_status',function()
    local u=fixture();u.status.current_soul=nil
    local r=run(u)
    assert(r.soul_available==false and r.skills==nil and r.attributes.mental==nil)
    assert(r.health.blood_count==4500 and #r.body.wounds==1)
    assert(has_unavailable(r,'skills') and has_unavailable(r,'personality'))
end)
test('unreadable_part_status_is_not_healthy',function()
    local u=fixture();u.body.components.body_part_status=nil
    local r=run(u)
    assert(r.body.parts[1].active_status_flags==nil)
    assert(has_unavailable(r,'body.parts[0].active_status_flags'))
end)

local function carried(id, whole, fraction, mode, computed)
    return {item={id=id,description='Item '..id,weight={whole=whole,fraction=fraction},
        flags={weight_computed=computed~=false}},mode=df.inv_item_role_type[mode or 'Worn']}
end
local function close(a,b) assert(math.abs(a-b)<0.0000001,tostring(a)..' ~= '..b) end
test('container_contents_and_stacks_are_counted_once',function()
    local u=fixture()
    u.inventory=vector({carried(20,17,511750),carried(21,3,572000,'Weapon')})
    local r=run(u,{inventory={{id=20,weight_raw={whole=17,fraction=511750},weight_computed=true,
        contents={{id=22,stack_size=5,weight_raw={whole=5,fraction=0},weight_computed=true}}}}})
    local e=r.encumbrance
    assert(e.weight_complete and e.root_item_count==2 and e.weighed_root_item_count==2)
    close(e.total_weight_kg,21.08375)
    close(r.inventory[1].contents[1].weight_kg,5)
    assert(e.heaviest_items[1].id==20 and e.heaviest_items[2].id==21)
    close(e.by_mode[1].weight_kg+e.by_mode[2].weight_kg,e.total_weight_kg)
    assert(e.capacity.available==false and e.load_penalty.available==false)
    assert(has_unavailable(r,'encumbrance.capacity') and has_unavailable(r,'encumbrance.load_penalty'))
end)
test('invalid_cache_is_unknown_not_zero_or_stale_mass',function()
    local u=fixture()
    u.inventory=vector({carried(20,99,0,'Worn',false),carried(21,2,750000,'Weapon')})
    local r=run(u,{inventory={{id=20,weight_raw={whole=99,fraction=0},weight_computed=false}}})
    local e=r.encumbrance
    assert(not e.weight_complete and e.total_weight_kg==nil and e.known_weight_kg==2.75)
    assert(e.unweighed_root_item_count==1 and e.unweighed_items[1].id==20)
    assert(r.inventory[1].weight_kg==nil and r.inventory[1].weight_unavailable_reason)
    assert(has_unavailable(r,'encumbrance.total_weight_kg'))
    -- Missing and malformed masses also cannot be presented as a complete sum.
    for _,weight in ipairs({{}, {whole=-1,fraction=0}, {whole=1,fraction=1000000}}) do
        u.inventory[0].item.flags.weight_computed=true;u.inventory[0].item.weight=weight
        assert(run(u).encumbrance.total_weight_kg==nil)
    end
end)
test('empty_inventory_and_zero_mass_remain_known',function()
    local u=fixture()
    local e=run(u).encumbrance
    assert(e.weight_complete and e.total_weight_kg==0 and #e.heaviest_items==0)
    u.inventory=vector({carried(20,0,0)})
    e=run(u).encumbrance
    assert(e.weight_complete and e.total_weight_kg==0 and e.weighed_root_item_count==1)
end)
test('repeated_inventory_references_are_not_double_counted',function()
    local u=fixture();local entry=carried(20,1,250000)
    u.inventory=vector({entry,entry})
    local e=run(u).encumbrance
    assert(e.weight_complete and e.total_weight_kg==1.25 and e.root_item_count==1)
    assert(e.inventory_entry_count==2 and e.weighed_root_item_count==1)
end)
test('weight_aggregation_is_independent_of_inventory_output_limits',function()
    local u=fixture();local inventory={}
    for id=1,121 do inventory[#inventory+1]=carried(id,1,0) end
    u.inventory=vector(inventory)
    local e=run(u,{inventory={},inventory_truncated=true}).encumbrance
    assert(e.weight_complete and e.total_weight_kg==121 and e.root_item_count==121)
    assert(#e.heaviest_items==10 and e.heaviest_items[1].id==1 and e.heaviest_items[10].id==10)
end)
test('weight_scan_limit_and_missing_entries_are_explicit',function()
    local u=fixture();local inventory={}
    for id=1,4097 do inventory[#inventory+1]=carried(id,1,0) end
    u.inventory=vector(inventory)
    local r=run(u)
    assert(not r.encumbrance.weight_complete and r.encumbrance.known_weight_kg==4096)
    assert(r.encumbrance.total_weight_kg==nil and r.truncated[1].path=='encumbrance.inventory_scan')
    u.inventory=vector({{}})
    local e=run(u).encumbrance
    assert(not e.weight_complete and e.unweighed_items[1].inventory_index==0)
end)

local hud_status={screen='viewscreen_dungeonmodest',adventure_menu='Default',ready_for_input=true,open_panels={}}
local function hud(label,value)
    return {height=77,rows={{y=75,text='             '..label},{y=76,text='             '..value}}}
end
test('hud_speed_uses_native_gait_and_preserves_zero',function()
    for _,value in ipairs({'0.471','0.000'}) do
        local r=run(fixture(),nil,hud('Walk',value),hud_status)
        assert(r.movement.displayed_speed.value==tonumber(value))
        assert(r.movement.displayed_speed.text==value and r.movement.displayed_speed.gait=='Walk')
        assert(r.movement.displayed_speed.units=='native_display')
        assert(r.movement.effective_rate==nil and r.health.recuperation_healing_rate==1000)
    end
end)
test('hidden_or_unrecognized_hud_does_not_produce_a_speed',function()
    local cases={
        {hud('Walk','0.471'),{screen='viewscreen_dungeonmodest',adventure_menu='Default',ready_for_input=true,modal={kind='help'}}},
        {hud('Walk','0.471'),{screen='viewscreen_dungeonmodest',adventure_menu='Default',ready_for_input=true,open_panels={'inventory'}}},
        {hud('Walk','0.471'),{screen='viewscreen_dungeonmodest',adventure_menu='Default',ready_for_input=false}},
        {hud('Price','0.471'),hud_status},
        {hud('Walk',' 0.471'),hud_status},
        {hud('Walk','0.471 some menu text'),hud_status},
        {{height=77,rows={{y=5,text='Walk'},{y=6,text='0.471'}}},hud_status},
    }
    for _,case in ipairs(cases) do
        local r=run(fixture(),nil,case[1],case[2])
        assert(r.movement.displayed_speed==nil and has_unavailable(r,'movement.displayed_speed'))
    end
end)
return {passed=#results,tests=results}
