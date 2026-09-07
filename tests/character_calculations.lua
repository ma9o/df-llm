-- Pure fixtures in DFHack Lua. No native unit, menu, clock, or inventory writes.
local source,burden_source=...
local version='v0.53.16 win64 STEAM'
local function flags(values) return setmetatable(values or {},{__index=function() return false end}) end
local function vector(values)
    local v={};for i,value in ipairs(values) do v[i-1]=value end
    return setmetatable(v,{__len=function() return #values end})
end
local fake_df=setmetatable({global={gamemode=df.game_mode.ADVENTURE,
    debug_turbospeed=false,debug_noeat=false,debug_nodrink=false,debug_nosleep=false,
    world={raws={creatures={action_strings={[0]='Walk',[1]='Fly',[2]='Swim',[3]='Crawl',[4]='Climb'}}}}}}, {__index=df})
local fake_dfhack={getDFVersion=function() return version end,getOSType=function() return 'windows' end,
    internal={getPE=function() return 1785767641 end},units={
        getNominalSkill=function(u,id) return u.skills[id] or 0 end,
        getMiscTrait=function(u,_,create) assert(create==false);return u.blood_trait end,
        isHidingCurse=function(u) return u.hiding_curse or false end,
        getPhysicalAttrValue=function(u,id)return u.body.physical_attrs[id].value end,
        getEffectiveSkill=function(u,id)return u.skills[id] or 0 end,
    }}
local model=assert(load(source,'character calculations fixture','t',setmetatable({df=fake_df,dfhack=fake_dfhack},{__index=_G})))()
local burden=assert(load(burden_source,'burden integration fixture','t',setmetatable({df=fake_df,dfhack=fake_dfhack},{__index=_G})))()
local function fixture()
    local gaits,indices={},{}
    for id,speed in ipairs({900,1000,5341,2990,6561}) do
        gaits[id-1]=vector({{full_speed=speed,start_speed=0,buildup_time=0,stealth_slows=0,
            flags=flags{},action_string_idx=id-1}});indices[id-1]=0
    end
    return {flags1=flags{},flags2=flags{calculated_bodyparts=true,vision_good=true},flags3=flags{},
        counters={soldier_mood=-1,nausea=0,winded=0,stunned=0,dizziness=0,pain=0,webbed=0,unconscious=0},
        counters2={fever=0,exhaustion=0,hunger_timer=0,thirst_timer=0,sleepiness_timer=0,paralysis=0},
        mood=-1,profession=df.profession.HAMMERMAN,uwss_speed_perc=100,uwss_speed_add=0,
        uwss_add_caste_flag=flags{},uwss_remove_caste_flag=flags{},
        body={size_info={size_cur=5731,size_base=5600},physical_attrs={
            [0]={value=1100,soft_demotion=0},[1]={value=1100,soft_demotion=0}},body_plan={gait_info=gaits}},
        enemy={gait_index=indices},skills={},job={gait_buildup=0,climb_hold={x=-30000},hold_itid=-1},
        status2={liquid_depth=0,liquid_type={whole=0},limbs_stand_count=2,limbs_stand_max=2,limbs_fly_count=0,limbs_fly_max=0},
        relationship_ids={[df.unit_relationship_type.Draggee]=-1},inventory=vector({})}
end
local next_item_id=0
local function carried(whole,fraction,mode,armor,computed)
    next_item_id=next_item_id+1
    return {mode=df.inv_item_role_type[mode or 'Weapon'],item={id=next_item_id,weight={whole=whole,fraction=fraction},
        flags={weight_computed=computed~=false},isArmor=function() return armor==true end}}
end
local function run(u,creature_flags)
    local out={physiology={effective_creature_flags=flags(creature_flags)},encumbrance={},movement={},semantics={},unavailable={}}
    local helpers={text=function(v) return v end,caste={flags=flags(creature_flags)},read=function(path,fn)
        local ok,value=pcall(fn)
        if ok then return value end
        out.unavailable[#out.unavailable+1]={path=path,reason=tostring(value)}
    end,unavailable=function(path,reason)out.unavailable[#out.unavailable+1]={path=path,reason=reason}end}
    burden.apply(u,out,helpers)
    model.apply(u,out,helpers)
    return out
end
local result={}
local function test(name,fn) fn();result[#result+1]=name end
local function close(a,b) assert(math.abs(a-b)<1e-9,tostring(a)..' ~= '..tostring(b)) end
local function speed(r) assert(r.movement.effective_speed.available,require('json').encode(r.unavailable));return r.movement.effective_speed end

test('every_need_threshold_is_inclusive_and_reports_the_next_stage',function()
    for kind,thresholds in pairs({hunger={57600,172800,1209600,2592000},thirst={57600,115200,172800,345600},
            sleep={115200,172800,259200,345600,864000},blood_thirst={172800,1209600,2419200}}) do
        for index,threshold in ipairs(thresholds) do
            local before=model.need(kind,threshold-1,true)
            assert(before.severity==index-1 and before.next_stage.counter==threshold and before.next_stage.remaining_counter==1)
            assert(model.need(kind,threshold,true).severity==index)
            assert(model.need(kind,threshold+1,true).severity==index)
        end
    end
    assert(model.need('hunger',2592000,true).label=='Starving')
    assert(model.need('thirst',345600,true).label=='Dehydrated')
    assert(model.need('sleep',864000,true).label=='Slumberous')
end)
test('zero_needs_exemptions_and_missing_requirements_are_distinct',function()
    local r=model.need('hunger',0,true);assert(r.counter==0 and r.severity==0 and r.native_label==nil and r.required)
    r=model.need('thirst',345600,false);assert(r.counter==345600 and not r.required and r.state=='exempt' and r.next_stage==nil)
    assert(not pcall(model.need,'sleep',0,nil))
    assert(not pcall(model.need,'sleep',nil,true))
end)
test('legacy_speed_build_gate_does_not_gate_the_burden_helper',function()
    assert(model.supported(version,'windows',1785767641))
    assert(not model.supported(version,'linux',1785767641))
    assert(not model.supported(version,'windows',1785767642))
    version='v0.53.17 win64 STEAM'
    local r=run(fixture())
    assert(r.encumbrance.capacity.available and r.encumbrance.load_penalty.available)
    assert(r.encumbrance.burden.available)
    assert(not r.movement.effective_speed.available and not r.physiology.interpreted_needs.available and #r.unavailable==2)
    version='v0.53.16 win64 STEAM'
end)
test('live_load_regression_matches_native_hud_and_unloaded_counterfactual',function()
    local u=fixture();u.inventory=vector({carried(98,462250)})
    local r=run(u);local s=speed(r)
    close(r.encumbrance.capacity.weight_kg,63.04)
    assert(s.movement_cost==2023 and s.displayed_text=='0.471' and s.unloaded.displayed_text=='1.000')
    close(s.value,1000/2123)
    assert(r.encumbrance.load_penalty.movement_cost_added==1123)
    close(r.encumbrance.load_penalty.speed_reduction_percent,52.896844088554)
    assert(r.encumbrance.burden.label=='Overburdened' and r.encumbrance.burden.overburdened)
    close(r.encumbrance.burden.thresholds.overburdened_above_kg,94.56)
end)
test('native_load_quantization_and_first_penalty',function()
    local u=fixture()
    u.inventory=vector({carried(63,49999)})
    assert(run(u).encumbrance.load_penalty.movement_cost_added==0)
    u.inventory=vector({carried(63,50000)})
    assert(run(u).encumbrance.load_penalty.movement_cost_added==1)
    u.inventory=vector({})
    local r=run(u);assert(r.encumbrance.load_penalty.effective_weight_kg==0 and r.encumbrance.load_penalty.applied==false)
    assert(speed(r).displayed_text=='1.000' and r.encumbrance.load_penalty.speed_reduction_percent==0)
end)
test('armor_discount_rounds_each_mass_part_and_only_applies_to_native_modes',function()
    local u=fixture();u.skills[df.job_skill.ARMOR]=2
    u.inventory=vector({carried(27,307500,'Worn',true),carried(3,500000,'Weapon',true),carried(17,511750,'Worn',false)})
    local r=run(u).encumbrance.load_penalty
    -- 21.249843 (native separate-part rounding) + 3.5 + 17.51175.
    close(r.effective_weight_kg,42.261593);assert(r.discounted_item_count==1)
    u.skills[df.job_skill.ARMOR]=1
    close(run(u).encumbrance.load_penalty.effective_weight_kg,48.31925)
    u.skills[df.job_skill.ARMOR]=15
    u.inventory=vector({carried(27,307500,'WrappedAround',true)})
    close(run(u).encumbrance.load_penalty.effective_weight_kg,0)
end)
test('container_root_cache_includes_contents_once',function()
    local u=fixture();local bag=carried(17,511750,'Worn',false)
    bag.item.contents=vector({carried(5,0)})
    u.inventory=vector({bag})
    close(run(u).encumbrance.load_penalty.effective_weight_kg,17.51175)
end)
test('invalid_weight_preserves_capacity_and_needs_but_not_false_zero_speed',function()
    local u=fixture();u.inventory=vector({carried(98,462250,'Weapon',false,false)})
    local r=run(u)
    assert(r.encumbrance.capacity.available and r.physiology.interpreted_needs.available)
    assert(not r.encumbrance.load_penalty.available and not r.movement.effective_speed.available)
    assert(not r.encumbrance.burden.available and r.encumbrance.burden.overburdened==nil)
    assert(#r.unavailable==3)
end)
test('modal_or_absent_ascii_is_not_a_calculation_dependency',function()
    -- Fake globals contain no UI/game object or input functions at all.
    local r=run(fixture());assert(speed(r).displayed_text=='1.000' and r.physiology.interpreted_needs.available)
end)
test('native_need_effects_use_864000_for_the_last_sleep_stage',function()
    local u=fixture();u.skills[df.job_skill.ARMOR]=20
    local skill_state={counters=u.counters,counters2=u.counters2,vision=true,mood=-1}
    u.counters2.sleepiness_timer=846000
    local r=run(u);assert(model.skill(20,skill_state)==10 and speed(r).movement_cost==1000)
    u.counters2.sleepiness_timer=864000
    r=run(u);assert(model.skill(20,skill_state)==5 and speed(r).movement_cost==1100)
    u.counters2.sleepiness_timer=0;u.counters2.hunger_timer=2592000;u.counters2.thirst_timer=345600
    r=run(u);assert(model.skill(20,skill_state)==5 and speed(r).movement_cost==1300)
end)
test('health_penalties_martial_trance_and_load_comparison_are_separate',function()
    local u=fixture();u.counters.nausea=1;u.counters.pain=100;u.counters2.exhaustion=6000
    assert(speed(run(u)).movement_cost==3500)
    u.counters.soldier_mood=0
    assert(speed(run(u)).movement_cost==1500)
end)
test('current_gait_not_selected_menu_gait_controls_speed',function()
    local u=fixture();u.status={command_gait_index={[0]=99}}
    assert(speed(run(u)).gait_index==0)
    u.enemy.gait_index[0]=-1
    assert(not run(u).movement.effective_speed.available)
end)
test('gait_buildup_and_attribute_scaling_match_native_integer_arithmetic',function()
    local u=fixture();local g=u.body.body_plan.gait_info[0][0]
    g.full_speed=450;g.start_speed=675;g.buildup_time=5;g.flags=flags{strength=true,agility=true,layers_slow=true}
    u.job.gait_buildup=2
    local s=speed(run(u))
    -- Base current cost 585, score 1100+1100+977, bounds 300..5700.
    assert(s.movement_cost==520 and s.at_full_gait.movement_cost==400)
    u.job.gait_buildup=5
    assert(speed(run(u)).movement_cost==400)
end)
test('movement_mode_and_liquid_depth_come_from_native_state',function()
    local u=fixture();u.flags1.on_ground=true
    assert(speed(run(u)).gait_type=='CRAWL' and speed(run(u)).movement_cost==2990)
    u.flags1.on_ground=false;u.flags2.swimming=true
    assert(speed(run(u)).gait_type=='SWIM' and speed(run(u)).movement_cost==5341)
    u.skills[df.job_skill.SWIMMING]=2
    assert(speed(run(u,{CAN_SWIM=true})).movement_cost==5073)
    u.flags2.swimming=false;u.job.hold_itid=22
    assert(speed(run(u)).gait_type=='CLIMB')
    u.job.hold_itid=-1
    assert(speed(run(u,{FLIER=true})).gait_type=='FLY')
    u.status2.liquid_depth=2
    assert(speed(run(u)).movement_cost==1200)
    u.status2.liquid_type.whole=2097152
    assert(speed(run(u)).movement_cost==1500)
end)
test('curse_modifiers_sneaking_and_stance_are_accounted_for',function()
    local u=fixture();u.uwss_speed_perc=200;u.uwss_speed_add=100
    u.flags1.hidden_in_ambush=true;u.body.body_plan.gait_info[0][0].stealth_slows=20
    u.status2.limbs_stand_max=4;u.status2.limbs_stand_count=3
    assert(speed(run(u)).movement_cost==1160)
end)
test('native_clamp_and_ignored_load_have_zero_false_slowdown',function()
    local u=fixture();u.mood=5;u.counters.nausea=1;u.counters.dizziness=1;u.inventory=vector({carried(98,462250)})
    local r=run(u);assert(speed(r).movement_cost==9999 and r.encumbrance.load_penalty.speed_reduction_percent==0)
    u.flags3.ghostly=true
    r=run(u);assert(speed(r).movement_cost==900 and r.encumbrance.load_penalty.movement_cost_added==0)
end)
test('unsupported_mounted_vision_and_stale_body_states_are_explicit',function()
    local u=fixture();u.flags1.rider=true
    local r=run(u);assert(not r.encumbrance.capacity.available and not r.movement.effective_speed.available)
    assert(not r.encumbrance.burden.available)
    u.flags1.rider=false;u.flags2.vision_good=false
    r=run(u);assert(r.encumbrance.load_penalty.available and not r.movement.effective_speed.available)
    u.flags2.calculated_bodyparts=false
    r=run(u);assert(not r.encumbrance.capacity.available and r.physiology.interpreted_needs.available)
end)
test('native_overflow_and_missing_required_fields_are_not_estimates',function()
    local u=fixture();u.uwss_speed_add=2147483647
    assert(not run(u).movement.effective_speed.available)
    u=fixture();u.counters2.sleepiness_timer=nil
    local r=run(u);assert(not r.physiology.interpreted_needs.available and not r.movement.effective_speed.available)
end)
test('burden_uses_armor_discounts_and_does_not_invent_exemptions_from_speed_flags',function()
    local u=fixture();u.inventory=vector({carried(98,462250,'Worn',true)})
    u.skills[df.job_skill.ARMOR]=5
    assert(run(u).encumbrance.burden.state=='unburdened')
    u.skills[df.job_skill.ARMOR]=1;u.flags3.scuttle=true
    local r=run(u)
    assert(r.encumbrance.load_penalty.movement_cost_added==0)
    assert(r.encumbrance.burden.state=='overburdened')
end)
return result
