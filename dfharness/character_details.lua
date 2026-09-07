--@ module=true
--luacheck: globals factory
local function build(...)
-- Character-owned profiles and capabilities. Only loaded by character queries.
local u,out,h=...
local array,text,read,list,label=h.array,h.text,h.read,h.list,h.label
local function object() return require('json.internal'):newObject{} end
local function missing(path,reason) h.unavailable(path,reason);return {available=false,reason=reason} end
local budget={remaining=50000}
local omitted=array()
local function coverage()
    local brief=h.profile=='brief'
    out.coverage={sections=array(),unavailable_count=#out.unavailable,truncated_count=#out.truncated,
        complete=#out.unavailable==0 and #out.truncated==0,unexpanded_references=omitted,
        scope=brief and 'brief' or 'Character state and character-owned profiles; world references are not recursively expanded',
        profile_limits={nodes=50000,depth=10,vector_entries=4096,string_bytes=16000}}
    if brief then out.coverage.not_queried=array() end
    local function belongs(path,key)
        return path==key or path:sub(1,#key+1)==key..'.' or path:sub(1,#key+1)==key..'['
    end
    for _,key in ipairs({'identity','affiliation','health','body','conditions','physiology','appearance','attributes',
            'skills','performance_skills','needs','personality','preferences','inventory','encumbrance','movement',
            'relationships','companions','reputation','career','knowledge','abilities','combat','senses','activity','possessions','obligations','history','native_sheet'}) do
        if brief and not h.requested(key) then
            out.coverage.not_queried[#out.coverage.not_queried+1]=key
            out[key]=nil
        else
            local value=out[key]
            local entry={section=key,status=(value==nil or value.available==false) and 'unavailable' or 'available',
                unavailable_count=0,truncated_count=0}
            if value and value.present==false then entry.present=false end
            for _,missing_field in ipairs(out.unavailable) do
                if belongs(missing_field.path,key) then entry.unavailable_count=entry.unavailable_count+1 end
            end
            for _,truncation in ipairs(out.truncated) do
                if belongs(truncation.path,key) then entry.truncated_count=entry.truncated_count+1 end
            end
            if entry.status=='available' and (entry.unavailable_count>0 or entry.truncated_count>0) then entry.status='partial' end
            out.coverage.sections[#out.coverage.sections+1]=entry
        end
    end
end

-- Reflect only explicitly selected character profiles. Check field metadata
-- before touching a value; never enumerate an untagged union or follow a
-- reference into the world's object graph. All output is plain data.
local references={unit=true,historical_figure=true,historical_entity=true,world_site=true,
    artifact_record=true,world=true,item=true,building=true,army=true,activity_entry=true}
local function reference_type(name)
    return references[name] or name:match('^item_') and not name:match('^item_power') or name:match('^building_')
end
local union_tags={[df.entity_event]=df.entity_event_type,[df.agreement_details]=df.agreement_details_type}
local function world_reference(value,type_name,path)
    if not value then return {present=false} end
    local r={reference_type=type_name,expanded=false}
    if type_name~='world' then
        r.id=read(path..'.id',function() return value.id end)
    end
    return r
end
local snapshot
snapshot=function(value,path,depth)
    depth=depth or 0
    if depth>10 or budget.remaining<=0 then
        out.truncated[#out.truncated+1]={path=path,reason='Character profile depth or node limit',limit=depth>10 and 10 or 50000}
        return {available=false,reason='Profile output limit'}
    end
    budget.remaining=budget.remaining-1
    if value==nil then return {present=false} end
    local kind=type(value)
    if kind=='number' or kind=='boolean' then return value end
    if kind=='string' then
        if #value>16000 then
            out.truncated[#out.truncated+1]={path=path,total=#value,limit=16000,unit='bytes'}
            value=value:sub(1,16000)
        end
        return text(value)
    end
    local native_kind=value._kind
    if native_kind=='primitive' then
        if type(value._type)=='string' and value._type:match('^shared_ptr<') then
            error('DFHack does not expose the fields of this shared-pointer record',0)
        end
        local v=value.value
        assert(type(v)=='string' or type(v)=='number' or type(v)=='boolean','Unsupported primitive reference')
        return snapshot(v,path,depth+1)
    elseif native_kind=='bitfield' then
        local result=object()
        for k,v in pairs(value) do if type(k)=='string' then result[k]=v end end
        return result
    elseif native_kind=='container' then
        return list(value,4096,path,function(v,i) return snapshot(v,path..'['..i..']',depth+1) end)
    elseif native_kind=='struct' then
        assert(not value._type._union,'Union requires a verified active-member tag')
        local result,labels=object(),object()
        for name,meta in pairs(value._type._fields) do
            if meta.offset~=nil and meta.mode>=1 and meta.mode<=7 then
                local p=path..'.'..name
                if name:match('^texpos') or name=='pool_id' or name=='mtx' or name=='debug' then
                    -- Renderer/allocation/debug metadata is not character state.
                elseif meta.type and meta.type._union then
                    local enum=union_tags[value._type]
                    local tag=enum and enum[value.type]
                    if enum==df.entity_event_type and tag=='artifact_was_destroyed' then tag='artifact_destroyed' end
                    if name=='data' and tag and meta.type._fields[tag] then
                        result[name]=read(p,function() return {tag=tag,value=snapshot(value[name][tag],p..'.'..tag,depth+1)} end)
                    else
                        result[name]=missing(p,'Union requires a verified active-member tag')
                    end
                elseif reference_type(meta.type_name or '') and (meta.mode==3 or meta.mode==7) then
                    result[name]=read(p,function()
                        if meta.mode==7 then return list(value[name],4096,p,function(v,i)
                            return world_reference(v,meta.type_name,p..'['..i..']') end) end
                        return world_reference(value[name],meta.type_name,p)
                    end)
                    omitted[#omitted+1]={path=p,reason='World object references are represented by IDs without recursively expanding their state'}
                else
                    result[name]=read(p,function() return snapshot(value[name],p,depth+1) end)
                    if meta.type and meta.type._kind=='enum-type' and type(result[name])=='number' then
                        labels[name]=meta.type[result[name]] or tostring(result[name])
                    end
                end
            end
        end
        if next(labels) then result.enum_labels=labels end
        return result
    end
    error('Unsupported profile value type: '..tostring(native_kind),0)
end
local function section(source,names,path)
    local result=object()
    for _,name in ipairs(names) do
        result[name]=read(path..'.'..name,function() return snapshot(source[name],path..'.'..name) end)
    end
    return result
end
local function profile(source,name,path)
    local result=read(path,function()
        assert(source,'Parent character profile is unavailable')
        return snapshot(source[name],path)
    end)
    return result or {available=false,reason='Character profile could not be read; see unavailable'}
end
local function named(kind,id,path)
    return h.named_reference(kind,id,path)
end
local function unit_ref(id,_path)
    local r={id=id}
    if id and id>=0 then
        local target=df.unit.find(id)
        if target then
            r.name=text(dfhack.units.getReadableName(target))
            r.hist_figure_id=target.hist_figure_id
        else r.loaded=false end
    end
    return r
end
local function native_flags(v)
    local r=object();for k,value in pairs(v) do if type(k)=='string' then r[k]=value end end;return r
end
local caste=h.caste
-- Shared physical and combat readings, before the optional large profiles.
out.physiology=object()
out.physiology.effective_creature_flags=read('physiology.effective_creature_flags',function()
    local r=h.health.creature_flags(u,{'NO_EAT','NO_DRINK','NO_SLEEP','NOBREATHE','NOEXERT','NOPAIN','NOSTUN','BLOODSUCKER',
        'NOT_LIVING','DIURNAL','NOCTURNAL','CREPUSCULAR','ALL_ACTIVE'})
    for name,reason in pairs(r.unavailable or {})do
        h.unavailable('physiology.effective_creature_flags.'..name,reason)
    end
    return r.flags
end)
if h.burden then h.burden.apply(u,out,h)end
if h.calculations then
    h.calculations.apply(u,out,h)
else
    out.physiology.interpreted_needs=missing('physiology.interpreted_needs','Character calculation module was not supplied')
end
out.combat=object()
if h.interfaces then out.combat.interface=h.interfaces.combat end
out.combat.opponent=profile(u,'opponent','combat.opponent')
out.combat.attacker_ids=profile(u.status,'attacker_ids','combat.attacker_ids')
out.combat.grapple_count=read('combat.grapple_count',function()return #u.status.wrestle_items end)
if h.profile=='brief' then coverage();return out end

local hf=read('historical_figure',function() return df.historical_figure.find(u.hist_figure_id) end)
local info=hf and hf.info
local soul=u.status.current_soul
out.affiliation=out.affiliation or object()

out.identity.native=section(u,{'profession','profession2','adjective','population_id','breed_id','hist_figure_id2',
    'birth_year_bias','birth_time_bias','curse_year','curse_time'},'identity.native')
out.identity.caste_description=caste and text(caste.description) or nil
out.identity.orientation=profile(soul,'orientation_flags','identity.orientation')
out.conditions=section(u,{'mood','moodstage','mood_copy','pregnancy_timer','pregnancy_caste','pregnancy_spouse',
    'ghost_info'},'conditions')
out.conditions.mood_name=label('mood_type',u.mood)
out.conditions.flags=object()
for _,name in ipairs({'flags1','flags2','flags3','flags4'}) do
    out.conditions.flags[name]=read('conditions.flags.'..name,function() return native_flags(u[name]) end)
end
out.conditions.modifiers=section(u,{'uwss_flag','uwss_add_caste_flag','uwss_remove_caste_flag',
    'uwss_add_property','uwss_remove_property','uwss_use_display_name','uwss_display_name_sing',
    'uwss_display_name_plur','uwss_display_name_adj','uwss_body_modifier','uwss_bp_modifer',
    'uwss_speed_add','uwss_speed_perc','uwss_att_change','uwss_skill_role_adjust','uwss_erratic_level'},'conditions.modifiers')
out.conditions.transformation=section(u.enemy,{'were_race','were_caste','normal_race','normal_caste',
    'undead','retraction_interaction'},'conditions.transformation')
out.conditions.historical_interactions=profile(info,'curse','conditions.historical_interactions')
out.health.native_counters=section(u,{'counters','counters2'},'health.native_counters')
out.health.diagnosis=profile(u,'health','health.diagnosis')
out.health.consumption_history=profile(u.status,'eat_history','health.consumption_history')
out.health.misc_traits=profile(u.status,'misc_traits','health.misc_traits')
out.health.syndrome_exposure=section(u.syndromes,{'reinfection_type','reinfection_count'},'health.syndrome_exposure')
out.body.healing=section(u,{'healing_rate','tendons_heal','ligaments_heal'},'body.healing')
out.body.layers=read('body.layers',function()
    local plan,components=u.body.body_plan,u.body.components
    return list(plan.layer_part,4096,'body.layers',function(bp,index)
        local p='body.layers['..index..']'
        local r={id=index,body_part_id=bp,layer_index=plan.layer_idx[index]}
        for _,name in ipairs({'layer_status','layer_wound_area','layer_cut_fraction','layer_dent_fraction','layer_effect_fraction'}) do
            r[name]=read(p..'.'..name,function() return snapshot(components[name][index],p..'.'..name) end)
        end
        return r
    end)
end)
for _,part in ipairs(out.body.parts or {}) do
    local p='body.parts['..part.id..']'
    part.temperature_raw=read(p..'.temperature_raw',function() return snapshot(u.status2.body_part_temperature[part.id],p..'.temperature_raw') end)
end

out.needs.has_unmet_psychological_needs=read('needs.has_unmet_psychological_needs',function()
    assert(soul,'No current soul');return soul.personality.flags.has_unmet_needs
end)

out.appearance=profile(u,'appearance','appearance')
out.appearance.body_modifier_definitions=caste and profile(caste,'body_appearance_modifiers','appearance.body_modifier_definitions') or nil
out.appearance.part_modifier_definitions=caste and profile(caste,'bp_appearance','appearance.part_modifier_definitions') or nil
out.appearance.color_definitions=caste and profile(caste,'color_modifiers','appearance.color_definitions') or nil

if soul then
    out.personality.details=section(soul.personality,{'ethics','preferences','mannerism','habit','flags',
        'temporary_trait_changes','memories','likes_outdoors','outdoor_dislike_counter','time_without_distress',
        'time_without_eustress','slack_end_year','slack_end_year_tick','temptation_greed','temptation_lust',
        'temptation_power','temptation_anger'},'personality.details')
    out.preferences=read('preferences',function()
        local target_fields={LikeCreature='creature_id',HateCreature='creature_id',LikeColor='color_id',LikeShape='shape_id',
            LikePlant='plant_id',LikeTree='plant_id',LikePoeticForm='poetic_form_id',LikeMusicalForm='musical_form_id',
            LikeDanceForm='dance_form_id',LikeItem='item_type',LikeFood='item_type'}
        return list(soul.preferences,4096,'preferences',function(pref,index)
            local p='preferences['..index..']'
            local r=section(pref,{'type','item_subtype','mattype','matindex','mat_state','flags','prefstring_seed'},p)
            r.type_name=label('unitpref_type',pref.type)
            local key=target_fields[r.type_name]
            if key then r[key]=pref[key] end
            if pref.mattype>=0 then r.material=read(p..'.material',function() return text(dfhack.matinfo.decode(pref.mattype,pref.matindex):toString()) end) end
            return r
        end)
    end)
    out.performance_skills=profile(soul,'performance_skills','performance_skills')
else
    out.preferences=missing('preferences','No current soul')
    out.performance_skills=missing('performance_skills','No current soul')
end

out.relationships=object()
out.relationships.unit_links=read('relationships.unit_links',function()
    local r=array()
    for id=0,#u.relationship_ids-1 do
        local target=u.relationship_ids[id]
        if target>=0 then r[#r+1]={type=label('unit_relationship_type',id),unit=unit_ref(target,'relationships.unit_links')} end
    end
    return r
end)
out.relationships.historical_links=read('relationships.historical_links',function()
    assert(hf,'No historical figure')
    return list(hf.histfig_links,4096,'relationships.historical_links',function(link,index)
        return {type=label('histfig_hf_link_type',link:getType()),strength=link.link_strength,
            target=named('historical_figure',link.target_hf,'relationships.historical_links['..index..'].target')}
    end)
end)
out.relationships.social=profile(info,'relationships','relationships.social')
if info and info.relationships then
    for _,key in ipairs({'hf_visual','hf_historical'}) do
        for _,record in ipairs(out.relationships.social[key] or {}) do
            if record.histfig_id then record.person=named('historical_figure',record.histfig_id,'relationships.social.'..key..'.person') end
        end
    end
end
out.relationships.recent_conversation_partners=read('relationships.recent_conversation_partners',function()
    return list(u.enemy.just_talked_unid,4096,'relationships.recent_conversation_partners',function(id) return unit_ref(id) end)
end)
out.affiliation.groups=read('affiliation.groups',function()
    assert(hf,'No historical figure')
    return list(hf.entity_links,4096,'affiliation.groups',function(link,index)
        return {type=label('histfig_entity_link_type',link:getType()),strength=link.link_strength,
            entity=named('historical_entity',link.entity_id,'affiliation.groups['..index..'].entity'),
            native=snapshot(link,'affiliation.groups['..index..'].native')}
    end)
end)
out.affiliation.site_links=hf and profile(hf,'site_links','affiliation.site_links') or nil
out.affiliation.occupations=profile(u,'occupations','affiliation.occupations')
out.reputation=profile(info,'reputation','reputation')
out.career=profile(info,'skills','career')
out.history=section(info,{'metaphysical','pets','personality','masterpieces','whereabouts','wounds'},'history')

out.companions=read('companions',function()
    local n=dfhack.units.getNemesis(u)
    if not n then return {present=false} end
    return {nemesis_id=n.id,group_leader_nemesis_id=n.group_leader_id,
        members=list(n.companions,4096,'companions.members',function(id,index)
            local r={nemesis_id=id};local member=df.nemesis_record.find(id)
            if member then
                r.unit=unit_ref(member.unit_id);r.group_leader_nemesis_id=member.group_leader_id
                if member.figure then r.hist_figure=named('historical_figure',member.figure.id,'companions.members['..index..'].hist_figure') end
            else r.loaded=false end
            return r
        end)}
end)
out.companions=out.companions or object()
out.companions.party=read('companions.party',function()
    return section(df.global.adventure.interactions,{'party_core_members','party_pets'},'companions.party')
end)

out.knowledge=profile(info,'known_info','knowledge')
if info and info.known_info then
    for _,spec in ipairs({{'known_written_contents','written_content','title'},
            {'known_poetic_forms','poetic_form','name'},{'known_musical_forms','musical_form','name'},
            {'known_dance_forms','dance_form','name'}}) do
        out.knowledge[spec[1]]=read('knowledge.'..spec[1],function()
            return list(info.known_info[spec[1]],4096,'knowledge.'..spec[1],function(id,index)
                local r={id=id}
                r.name=read('knowledge.'..spec[1]..'['..index..'].name',function()
                    local found=df[spec[2]].find(id)
                    if found then
                        local value=found[spec[3]]
                        return type(value)=='string' and text(value) or text(dfhack.translation.translateName(value,true))
                    end
                end)
                return r
            end)
        end)
    end
    for index,record in ipairs(out.knowledge.creature_knowledge or {}) do
        record.creature=read('knowledge.creature_knowledge['..(index-1)..'].creature',function()
            local all=df.global.world.raws.creatures
            local race=all.list_creature[record.combined_caste_id]
            local caste_index=all.list_caste[record.combined_caste_id]
            local creature=all.all[race]
            return {race=race,caste=caste_index,race_token=text(creature.creature_id),
                name=text(creature.caste[caste_index].caste_name[0])}
        end)
    end
end
out.knowledge.observed_traps=profile(u.status,'observed_traps','knowledge.observed_traps')
out.knowledge.recent_rumors=profile(u.enemy,'rumor_info','knowledge.recent_rumors')
out.knowledge.recent_witness_reports=profile(u.enemy,'witness_reports','knowledge.recent_witness_reports')

out.abilities=object()
out.abilities.native=profile(u,'usable_interaction','abilities.native')
out.abilities.body=read('abilities.body',function()
    return list(u.usable_interaction.own_interaction,4096,'abilities.body',function(index,slot)
        local ability=u.body.body_plan.interactions[index]
        return {index=index,type=label('body_action_type',ability.type),name=text(ability.interaction.adv_name),
            cooldown_raw=u.usable_interaction.own_interaction_delay[slot],
            definition=snapshot(ability.interaction,'abilities.body['..slot..'].definition')}
    end)
end)
out.abilities.granted=read('abilities.granted',function()
    return list(u.usable_interaction.interaction_id,4096,'abilities.granted',function(id,index)
        local effect=df.creature_interaction_effect.find(id)
        assert(effect,'Granted interaction effect could not be resolved')
        return {effect_id=id,last_checked_raw=u.usable_interaction.interaction_time[index],
            type=label('creature_interaction_effect_type',effect:getType()),
            name=read('abilities.granted['..index..'].name',function() return text(effect.interaction.adv_name) end),
            cooldown_raw=u.usable_interaction.interaction_delay[index],definition=snapshot(effect,'abilities.granted['..index..'].definition')}
    end)
end)

out.combat.natural_attacks=profile(u.body.body_plan,'attacks','combat.natural_attacks')
out.combat.last_hit=profile(u,'last_hit','combat.last_hit')
out.combat.attacker_countdowns=profile(u.status,'attacker_cntdn','combat.attacker_countdowns')
out.combat.wrestling=profile(u.status,'wrestle_items','combat.wrestling')
out.combat.side_id=u.enemy.combat_side_id
out.combat.modifiers=section(u.job,{'attack_chance_modifier','target_flags'},'combat.modifiers')
out.combat.kill_history=profile(info,'kills','combat.kill_history')
out.combat.attack_awareness=read('combat.attack_awareness',function()
    local a=u.enemy.attack_awareness;local r=array()
    for i=0,#a.unit_id-1 do
        if a.unit_id[i]>=0 then r[#r+1]={slot=i,unit=unit_ref(a.unit_id[i]),action_id=a.unit_mvid[i],
            precise_phase=a.precise_phase[i],absolute_season=a.abs_season[i],flags=native_flags(a.flag[i])} end
    end
    return r
end)
out.combat.command_flags=profile(u.status,'unit_command_flag','combat.command_flags')
out.combat.preferences=missing('combat.preferences',
    'Attack, dodge and charge-defense preference globals are not exposed by this DFHack build')
out.senses=section(u.job,{'vision_x','vision_y','vision_z','vision_angle'},'senses')
out.senses.detection=read('senses.detection',function()
    local d=u.enemy.detection_info;local r={count=d.last_spotted_unid_num,units=array()}
    assert(r.count>=0 and r.count<=#d.last_spotted_unid,'Invalid detection count')
    for i=0,r.count-1 do r.units[#r.units+1]=unit_ref(d.last_spotted_unid[i]) end
    return r
end)
out.senses.smell=read('senses.smell',function()
    return section(df.global.adventure,{'odor_race','odor_caste','odor_death',
        'travel_odor_race','travel_odor_caste','travel_odor_death'},'senses.smell')
end)
out.activity.current_job=read('activity.current_job',function()
    local job=u.job.current_job
    if not job then return {present=false} end
    return {id=job.id,type=label('job_type',job.job_type),flags=snapshot(job.flags,'activity.current_job.flags')}
end)
out.activity.memberships=section(u,{'social_activities','conversations','activities','individual_drills'},'activity.memberships')
if h.interfaces then out.activity.conversation_interface=h.interfaces.conversation end
out.activity.travel=profile(u.enemy,'travel_log','activity.travel')
out.activity.adventure=read('activity.adventure',function()
    return section(df.global.adventure,{'wait_timer','long_action_duration','player_control_state','tactical_mode',
        'sleeping','sleep_interrupt','local_sleep_origination','sleep_hours','sleep_until_dawn',
        'started_sleep_at_dawn','sleep_sleep','sleeping_indoors','sleeping_underground'},'activity.adventure')
end)
if h.next_dawn then
    out.activity.next_dawn=h.next_dawn
    if not h.next_dawn.available then h.unavailable('activity.next_dawn',h.next_dawn.reason) end
end
out.history.reports=read('history.reports',function()
    local result=array()
    for kind=0,#u.reports.log-1 do
        local reports={type=label('unit_report_type',kind)}
        reports.entries=list(u.reports.log[kind],4096,'history.reports['..kind..'].entries',function(id,index)
            local report=df.report.find(id)
            if not report then return {id=id,available=false,reason='Report is no longer retained by the game'} end
            return section(report,{'id','text','type','year','time','flags'},'history.reports['..kind..'].entries['..index..']')
        end,true)
        result[#result+1]=reports
    end
    return result
end)
out.activity.actions=read('activity.actions',function()
    return list(u.actions,4096,'activity.actions',function(action,index)
        local r={id=action.id,type=label('unit_action_type',action.type),active=action.type~=df.unit_action_type.None}
        if r.active then
            local tag=df.unit_action_type.attrs[action.type].tag
            if tag and #tag>0 then r.data=snapshot(action.data[tag],'activity.actions['..index..'].data')
            else r.data=missing('activity.actions['..index..'].data','No verified union tag for this action type') end
        end
        return r
    end)
end)
out.movement.all_gaits=read('movement.all_gaits',function()
    local r=array()
    for gait_type=0,df.gait_type._last_item do
        r[#r+1]={type=label('gait_type',gait_type),gaits=list(u.body.body_plan.gait_info[gait_type],4096,
            'movement.all_gaits['..gait_type..']',function(gait,index)
                local e=snapshot(gait,'movement.all_gaits['..gait_type..']['..index..']')
                e.index=index;e.name=text(df.global.world.raws.creatures.action_strings[gait.action_string_idx])
                return e
            end)}
    end
    return r
end)
out.movement.native=section(u.job,{'move_momentum_dir','gait_buildup','climb_hold','hold_itid'},'movement.native')
out.movement.control=section(u,{'dungeon_control','on_item_id','mount_type','follow_distance','owner_type'},'movement.control')
out.movement.path=section(u.path,{'dest','goal'},'movement.path')

out.possessions=section(u,{'owned_items','traded_items','corpse_parts'},'possessions')
out.possessions.coins=array()
out.possessions.item_familiarity=profile(u,'used_items','possessions.item_familiarity')
out.abilities.items=array()
local function inventory_details(items)
    for _,item in ipairs(items or {}) do
        local native=df.item.find(item.id)
        if native then
            item.value=read('inventory['..item.id..'].value',function() return dfhack.items.getValue(native) end)
            item.flags=profile(native,'flags','inventory['..item.id..'].flags')
            item.magic=read('inventory['..item.id..'].magic',function()
                local magic=native:getMagic()
                if not magic then return {present=false} end
                local powers=list(magic.power,4096,'inventory['..item.id..'].magic.powers',function(power,index)
                    local p='inventory['..item.id..'].magic.powers['..index..']'
                    local r=snapshot(power,p)
                    r.interaction=read(p..'.interaction',function() return snapshot(df.interaction.find(power.interaction_index),p..'.interaction') end)
                    return r
                end)
                out.abilities.items[#out.abilities.items+1]={item_id=item.id,description=item.description,powers=powers}
                return {present=true,powers=powers}
            end)
            if item.type=='COIN' then out.possessions.coins[#out.possessions.coins+1]={id=item.id,
                description=item.description,material=item.material,count=item.stack_size,weight_kg=item.weight_kg} end
        end
        if item.contents_truncated then out.truncated[#out.truncated+1]={path='inventory['..item.id..'].contents',
            reason='Inventory depth, item count or cycle limit',total=item.contents_total} end
        inventory_details(item.contents)
    end
end
inventory_details(out.inventory)
if out.inventory_truncated then out.truncated[#out.truncated+1]={path='inventory',total=#u.inventory,limit=4096} end
out.possessions.account=section(u.job,{'account','satisfaction'},'possessions.account')
out.possessions.coin_debts=read('possessions.coin_debts',function()
    return list(u.status.coin_debts,4096,'possessions.coin_debts',function(debt)
        return {recipient=unit_ref(debt.recipient),amount_raw=debt.amount}
    end)
end)
out.possessions.historical_inventory=profile(info,'books','possessions.historical_inventory')
out.possessions.assigned_buildings=read('possessions.assigned_buildings',function()
    return list(u.owned_buildings,4096,'possessions.assigned_buildings',function(b) return {id=b.id} end)
end)

out.obligations=section(u.status,{'demands','complaints','requests','parleys','commands',
    'last_command_received_year','last_command_received_season_count'},'obligations')
out.obligations.sleep_permissions=read('obligations.sleep_permissions',function()
    local a=df.global.adventure
    return list(a.sleep_permission_stid,4096,'obligations.sleep_permissions',function(id,i)
        return {site=named('world_site',id,'obligations.sleep_permissions['..i..'].site'),
            building_id=a.sleep_permission_srbid[i],timer_raw=a.sleep_permission_timer[i]}
    end)
end)
out.obligations.journal=read('obligations.journal',function()
    return list(df.global.game.main_interface.adventure.journal_outliner.agreement_entry,4096,'obligations.journal',function(entry,index)
        local p='obligations.journal['..index..']'
        local r=section(entry,{'list_name','simple_list_name','p_list_name','main_text_box','squad_order_repeatable'},p)
        if entry.ag then r.agreement=snapshot(entry.ag,p..'.agreement') end
        if entry.so then r.squad_order=snapshot(entry.so,p..'.squad_order') end
        if entry.sq then r.squad_id=entry.sq.id end
        return r
    end)
end)
out.obligations.chosen=read('obligations.chosen',function()
    local a=df.global.adventure
    return {flags=native_flags(a.chosen_flags),deity=named('historical_figure',a.chosen_deity_hfid,'obligations.chosen.deity'),
        religion=named('historical_entity',a.chosen_religion_enid,'obligations.chosen.religion'),
        temple_site=named('world_site',a.chosen_temple_stid,'obligations.chosen.temple_site'),
        temple_location_id=a.chosen_temple_abid,priest=named('historical_figure',a.chosen_priest_hfid,'obligations.chosen.priest')}
end)

-- UI prose is read only if it actually belongs to this character and is open.
out.native_sheet=read('native_sheet',function()
    local sheet=df.global.game.main_interface.view_sheets
    if not sheet.open or sheet.active_sheet~=df.view_sheet_type.UNIT or sheet.active_id~=u.id then
        return {available=false,reason='Character sheet is not open for this adventurer'}
    end
    return section(sheet,{'active_sheet','active_sub_tab','raw_description','raw_current_thought','raw_thought_str',
        'thoughts_raw_memory_str','personality_raw_str','unit_health_raw_str','skill_description_raw_str',
        'kill_description_raw_str'},'native_sheet')
end)
if out.native_sheet and out.native_sheet.raw_description and #out.native_sheet.raw_description>0 then
    out.appearance.description_text=out.native_sheet.raw_description
else
    out.appearance.description_text=missing('appearance.description_text',
        'Native description is not populated for this adventurer; structured appearance is supplied without opening menus')
end
coverage()
out.semantics.profiles='Native character-owned records; enum_labels annotate numeric enums. present=false is an absent optional profile. World pointers are not followed'
out.semantics.item_value='DFHack base item value without a specific trader; not a guaranteed sale price'
return out

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
