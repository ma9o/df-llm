-- Native-shaped fixtures; no world objects are allocated or modified.
local source,health_source=...
local json=require('json.internal')
local function array() return json:newArray{} end
local function vector(values)
    local r={_kind='container'}
    for i,v in ipairs(values or {}) do r[i-1]=v end
    return setmetatable(r,{__len=function() return #values end})
end
local function record(values,metadata)
    values=values or {};local fields={}
    for k in pairs(values) do fields[k]={offset=0,mode=1,type_name='int32_t'} end
    for k,v in pairs(metadata or {}) do fields[k]=v end
    values._kind='struct';values._type={_fields=fields}
    return values
end
local function flags(values)
    local r=values or {}
    return setmetatable(r,{__index=function() return false end})
end
local function fixture()
    local empty=function() return record{} end
    local unit={id=7,hist_figure_id=10,status={wrestle_items=vector{},current_soul={orientation_flags=record{},preferences=vector{},
        personality={flags={has_unmet_needs=false}}}},body={body_plan={layer_part=vector{},interactions=vector{},
        gait_info={}},components={}},enemy={just_talked_unid=vector{},
        attack_awareness={unit_id=vector{-1,-1}},detection_info={last_spotted_unid=vector{999,888},last_spotted_unid_num=0}},
        appearance=empty(),uwss_add_caste_flag=flags{},uwss_remove_caste_flag=flags{},
        relationship_ids=vector{},usable_interaction={own_interaction=vector{},interaction_id=vector{}},
        inventory=vector{},actions=vector{},reports={log=vector{}},job={},path={},syndromes={}}
    local hf={info={relationships=nil},histfig_links=vector{},entity_links=vector{}}
    local adventure={interactions={party_core_members=vector{10},party_pets=vector{}},sleep_permission_stid=vector{},chosen_flags=flags{}}
    local game={main_interface={adventure={journal_outliner={agreement_entry=vector{}}},view_sheets={open=false}}}
    local units={getReadableName=function(u) return 'Unit '..u.id end,getNemesis=function() return nil end}
    local fake_df=setmetatable({global={adventure=adventure,game=game,world={raws={creatures={}}}},
        historical_figure={find=function() return hf end},unit={find=function(id) return {id=id,hist_figure_id=id+100} end},
        item={find=function() return nil end}},{__index=df})
    local env=setmetatable({df=fake_df,dfhack={units=units}},{__index=_G})
    local reader=assert(load(source,'character profile fixture','t',env))
    local out={id=7,identity={},affiliation={},health={},body={parts={}},needs={},appearance={},personality={},
        movement={},activity={},inventory={},semantics={},unavailable=array(),truncated=array()}
    local function unavailable(path,reason) out.unavailable[#out.unavailable+1]={path=path,reason=reason} end
    local function read(path,fn)
        local ok,v=pcall(fn)
        if ok and v~=nil then return v end
        unavailable(path,ok and 'Unavailable' or tostring(v))
    end
    local function list(v,limit,path,convert)
        local r=array()
        if #v>limit then out.truncated[#out.truncated+1]={path=path,total=#v,limit=limit} end
        for i=0,math.min(#v,limit)-1 do
            local item=read(path..'['..i..']',function() return convert(v[i],i) end)
            if item~=nil then r[#r+1]=item end
        end
        return r
    end
    local helpers={array=array,read=read,list=list,unavailable=unavailable,
        text=function(v) if type(v)=='table' then return v.value end;return v end,
        label=function(enum,id) return df[enum][id] or tostring(id) end,
        named_reference=function(_,id) return {id=id,name='Named reference'} end,
        caste={flags=flags{},description='Fixture creature'}}
    units.getCasteRaw=function()return helpers.caste end
    helpers.health=assert(load(health_source,'health profile fixture','t',env))({array=array})
    return {u=unit,hf=hf,df=fake_df,game=game,out=out,helpers=helpers,env=env,
        run=function() return reader(unit,out,helpers) end}
end
local results=array()
local function test(name,fn) fn();results[#results+1]=name end
local function coverage(r,section)
    for _,entry in ipairs(r.coverage.sections) do if entry.section==section then return entry end end
    error('Missing coverage: '..section)
end
test('false_zero_absent_and_unavailable_profiles_are_distinct',function()
    local f=fixture();f.hf.info.reputation=nil;f.hf.info.skills=record{account_balance=0}
    local r=f.run()
    assert(r.needs.has_unmet_psychological_needs==false)
    assert(r.reputation.present==false and coverage(r,'reputation').present==false)
    assert(r.career.account_balance==0)
    assert(r.performance_skills.present==false)
    local f2=fixture();f2.hf.info=nil;r=f2.run()
    assert(r.reputation.available==false and r.reputation.present==nil)
    assert(coverage(r,'reputation').status=='unavailable')
end)
test('methods_and_unknown_unions_are_never_read',function()
    local f=fixture();local touches=0
    f.u.appearance=record({size_modifier=100},
        {method={offset=0,mode=8,type_name='function'},
         unsafe={offset=0,mode=5,type={_union=true}}})
    setmetatable(f.u.appearance,{__index=function(_,key)
        if key=='method' or key=='unsafe' then touches=touches+1;error('Unsafe field access') end
    end})
    local r=f.run()
    assert(touches==0 and r.appearance.size_modifier==100)
    assert(r.appearance.unsafe.available==false and r.appearance.method==nil)
end)
test('world_references_return_ids_without_following_the_object_graph',function()
    local f=fixture();local reference=setmetatable({id=55},{__index=function() error('Reference expanded') end})
    f.hf.info.books=record({artifacts_held=vector{reference}},
        {artifacts_held={offset=0,mode=7,type_name='artifact_record'}})
    local r=f.run();local ref=r.possessions.historical_inventory.artifacts_held[1]
    assert(ref.id==55 and ref.expanded==false and #r.coverage.unexpanded_references==1)
end)
test('tagged_quest_and_rumor_unions_select_only_the_active_member',function()
    local f=fixture();local touched=0
    local data=setmetatable({OfferService=record{served_entity=123}},
        {__index=function() touched=touched+1;error('Inactive union accessed') end})
    local detail={_kind='struct',_type=df.agreement_details,type=df.agreement_details_type.OfferService,data=data}
    f.hf.info.reputation=record{quest=detail}
    local rumor={_kind='struct',_type=df.entity_event,type=df.entity_event_type.artifact_was_destroyed,
        data=setmetatable({artifact_destroyed=record{artifact_id=987}},getmetatable(data))}
    f.hf.info.skills=record{rumor=rumor}
    local r=f.run()
    assert(touched==0 and r.reputation.quest.data.tag=='OfferService')
    assert(r.reputation.quest.data.value.served_entity==123)
    assert(r.career.rumor.data.value.artifact_id==987)
end)
test('abilities_use_body_plan_indexes_and_keep_zero_cooldowns',function()
    local f=fixture()
    f.u.usable_interaction.own_interaction=vector{2}
    f.u.usable_interaction.own_interaction_delay=vector{0}
    f.u.body.body_plan.interactions={[2]={type=df.body_action_type.CAN_DO_INTERACTION,
        interaction=record{adv_name='Fixture spell',wait_period=10}}}
    local r=f.run()
    assert(r.abilities.body[1].index==2 and r.abilities.body[1].name=='Fixture spell')
    assert(r.abilities.body[1].cooldown_raw==0)
end)
test('granted_abilities_resolve_effect_ids_and_fail_explicitly_if_missing',function()
    local f=fixture()
    f.u.usable_interaction.interaction_id=vector{123,456}
    f.u.usable_interaction.interaction_time=vector{0,0}
    f.u.usable_interaction.interaction_delay=vector{0,0}
    f.df.creature_interaction_effect={find=function(id)
        if id==123 then return record({interaction=record{adv_name='Granted fixture'},
            getType=function() return df.creature_interaction_effect_type.CAN_DO_INTERACTION end},
            {getType={offset=0,mode=8,type_name='function'}}) end
    end}
    local r=f.run()
    assert(#r.abilities.granted==1 and r.abilities.granted[1].name=='Granted fixture')
    assert(coverage(r,'abilities').status=='partial')
end)
test('effective_creature_needs_honor_added_and_removed_flags',function()
    local f=fixture();f.helpers.caste.flags.NO_EAT=true
    f.u.uwss_remove_caste_flag.NO_EAT=true;f.u.uwss_add_caste_flag.NO_DRINK=true
    local r=f.run()
    assert(r.physiology.effective_creature_flags.NO_EAT==false)
    assert(r.physiology.effective_creature_flags.NO_DRINK==true)
    assert(r.physiology.effective_creature_flags.NO_SLEEP==false)
end)
test('opaque grapple profiles retain count and mark unsupported detail in coverage',function()
    local f=fixture()
    f.u.status.wrestle_items=vector{setmetatable({_kind='primitive',_type='shared_ptr<struct df::unit_item_wrestle>'},
        {__index=function()error('Opaque native record read')end})}
    local r=f.run()
    assert(r.combat.grapple_count==1 and #r.combat.wrestling==0 and coverage(r,'combat').status=='partial')
    local found=false
    for _,v in ipairs(r.unavailable)do
        if v.path=='combat.wrestling[0]' then
            found=v.reason:find('shared-pointer',1,true)~=nil
        end
    end
    assert(found)
end)
test('unused_detection_and_attack_slots_do_not_become_current_targets',function()
    local f=fixture();local r=f.run()
    assert(#r.senses.detection.units==0 and #r.combat.attack_awareness==0)
end)
test('active_actions_read_only_the_native_tagged_payload',function()
    local f=fixture();local touched=0
    f.u.actions=vector{{id=42,type=df.unit_action_type.Move,
        data=setmetatable({move=record{timer=0}},{__index=function() touched=touched+1;error('Inactive action data') end})},
        {id=43,type=df.unit_action_type.None,data=setmetatable({},{__index=function() touched=touched+1;error('Unused action data') end})}}
    local r=f.run()
    assert(touched==0 and r.activity.actions[1].active and r.activity.actions[1].data.timer==0)
    assert(not r.activity.actions[2].active and r.activity.actions[2].data==nil)
end)
test('native_sheet_text_must_match_the_open_unit_sheet',function()
    for _,case in ipairs({{open=false,active_sheet=df.view_sheet_type.UNIT,active_id=7},
            {open=true,active_sheet=df.view_sheet_type.ITEM,active_id=7},
            {open=true,active_sheet=df.view_sheet_type.UNIT,active_id=8}}) do
        local f=fixture();case.raw_description='Stale description';f.game.main_interface.view_sheets=case
        local r=f.run();assert(r.appearance.description_text.available==false)
    end
    local f=fixture();f.game.main_interface.view_sheets={open=true,active_sheet=df.view_sheet_type.UNIT,
        active_id=7,raw_description='Fresh fixture description'}
    local r=f.run();assert(r.appearance.description_text=='Fresh fixture description')
end)
test('profile_limits_are_reported_in_section_coverage',function()
    local f=fixture();local values={};for i=1,4097 do values[i]=i end
    f.hf.info.skills=record{skills=vector(values)}
    local r=f.run()
    assert(#r.career.skills==4096 and coverage(r,'career').truncated_count==1)
    assert(coverage(r,'career').status=='partial' and not r.coverage.complete)
end)
test('nested_inventory_truncation_is_not_reported_as_complete_coverage',function()
    local f=fixture();f.out.inventory={{id=23,contents_truncated=true}}
    local r=f.run()
    assert(coverage(r,'inventory').status=='partial' and coverage(r,'inventory').truncated_count==1)
end)
test('native_dawn_calculation_and_its_unavailability_share_character_activity_coverage',function()
    local f=fixture()
    f.helpers.next_dawn={available=true,phase=0,world_region_x=0,remaining_calendar_ticks=253}
    local r=f.run()
    assert(r.activity.next_dawn.available and r.activity.next_dawn.phase==0)
    f=fixture();f.helpers.next_dawn={available=false,reason='Unverified dawn model'}
    r=f.run()
    assert(r.activity.next_dawn.available==false)
    local found=false
    for _,v in ipairs(r.unavailable)do if v.path=='activity.next_dawn' then found=true end end
    assert(found and coverage(r,'activity').status=='partial')
end)
test('brief_never_resolves_history_and_only_claims_queried_coverage',function()
    local f=fixture();local touches=0
    f.df.historical_figure.find=function() touches=touches+1;error('Unrequested historical figure') end
    f.u.opponent=record{unit_id=-1};f.u.status.attacker_ids=vector{0,42}
    f.helpers.profile='brief'
    f.helpers.requested=function(path)
        return ({identity=true,movement=true,health=true,attributes=true,skills=true,inventory=true,encumbrance=true,
            physiology=true,combat=true})[path] or false
    end
    f.helpers.calculations={apply=function(_,out)
        out.physiology.interpreted_needs={available=true,thirst={counter=0,required=false}}
        out.movement.effective_speed={available=false,reason='Fixture missing gait'}
        f.helpers.unavailable('movement.effective_speed','Fixture missing gait')
    end}
    local r=f.run()
    assert(touches==0 and r.combat.opponent.unit_id==-1 and r.combat.attacker_ids[1]==0)
    assert(r.physiology.interpreted_needs.thirst.required==false)
    assert(r.coverage.scope=='brief' and #r.coverage.sections==9 and #r.coverage.not_queried==20)
    assert(coverage(r,'movement').status=='partial' and r.history==nil and r.affiliation==nil)
end)
return results
