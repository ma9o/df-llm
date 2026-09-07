--@ module=true
--luacheck: globals factory
local function build(...)
-- Read-only character sheet and the narrow progression sample for receipts.
-- No input, game mutation, or controller policy is applied by this reader.
local u, out, helpers = ...
local array = helpers.array
local brief=helpers.profile=='brief'
local progression=helpers.profile=='progress'
-- Select before evaluating a read, not after traversing a native profile.
-- Full status has no filter. This profile is deliberately a separate query.
local brief_fields={identity={english_name=true,age_years=true,profession=true,hist_figure_id=true},
    health=true,attributes=true,skills=true,inventory=true,encumbrance=true,
    physiology=true,movement={effective_speed=true},combat=true,soul=true}
local function requested(path)
    if not brief then return true end
    local root,field=path:match('^([^.%[]+)%.?([^.%[]*)')
    local selection=brief_fields[root]
    return selection==true or type(selection)=='table' and (field=='' or selection[field]==true)
end
local function text(value)
    -- DF vectors of string pointers expose .value, unlike inline strings.
    if type(value)~='string' and value~=nil then value=value.value end
    return helpers.text(value)
end
local function object() return require('json.internal'):newObject{} end
out.unavailable=array()
out.truncated=array()

local function unavailable(path, reason)
    if requested(path) then out.unavailable[#out.unavailable+1]={path=path,reason=reason} end
end

local function read(path, fn)
    if not requested(path) then return end
    local ok,value=pcall(fn)
    if ok and value~=nil then return value end -- Preserve false and zero.
    unavailable(path,ok and 'Not available in this character state' or tostring(value):sub(1,240))
end

local function fields(source, names, path)
    local result=object()
    for _,name in ipairs(names) do
        result[name]=read(path..'.'..name,function()
            local value=source[name]
            if type(value)=='string' then return text(value) end
            if type(value)=='number' or type(value)=='boolean' then return value end
        end)
    end
    return result
end

local function label(enum, id)
    return df[enum][id] or tostring(id)
end

local function flags(source)
    local result=array()
    for key,value in pairs(source) do
        if value==true then result[#result+1]=tostring(key) end
    end
    table.sort(result)
    return result
end

local function list(source, limit, path, convert, recent)
    local result=array()
    local total=#source
    if total>limit then out.truncated[#out.truncated+1]={path=path,total=total,limit=limit} end
    local first=recent and math.max(0,total-limit) or 0
    for index=first,math.min(total-1,first+limit-1) do
        local value=read(path..'['..index..']',function() return convert(source[index],index) end)
        if value~=nil then result[#result+1]=value end
    end
    return result
end

local function translated(name)
    return text(dfhack.translation.translateName(name,true))
end

local function named_reference(kind, id, path)
    local result={id=id}
    if id and id>=0 then
        result.name=read(path..'.name',function()
            local found=df[kind].find(id)
            if found then return translated(found.name) end
        end)
    end
    return result
end

local function attributes(source, enum_name, getter, path)
    local result=array()
    for id=math.max(0,df[enum_name]._first_item),df[enum_name]._last_item do
        local attr=source[id]
        local entry=fields(attr,progression and {'value'} or {'value','max_value','soft_demotion'},path..'['..id..']')
        entry.id=id;entry.name=label(enum_name,id)
        if not progression then
            entry.effective=read(path..'['..id..'].effective',function() return getter(u,id) end)
        end
        result[#result+1]=entry
    end
    return result
end

local function skills(soul)
    return list(soul.skills,300,'skills',function(skill,index)
        local path='skills['..index..']'
        local entry=fields(skill,progression and {'id','rating','experience'}
            or {'id','rating','experience','rusty','natural_skill_lvl'},path)
        entry.name=label('job_skill',skill.id)
        entry.rating_name=read(path..'.rating_name',function() return text(df.skill_rating.attrs[skill.rating].caption) end)
        entry.next_level_xp_threshold=read(path..'.next_level_xp_threshold',function() return df.skill_rating.attrs[skill.rating].xp_threshold end)
        entry.total_experience=read(path..'.total_experience',function() return dfhack.units.getExperience(u,skill.id,true) end)
        if not progression then
            entry.caption=read(path..'.caption',function() return text(df.job_skill.attrs[skill.id].caption) end)
            entry.effective=read(path..'.effective',function() return dfhack.units.getEffectiveSkill(u,skill.id) end)
        end
        return entry
    end)
end

if progression then
    -- Stop before touching inventory, anatomy, needs, history, UI or effective
    -- attribute/skill calculations. These are stored values and native XP.
    local soul=read('soul',function() return u.status.current_soul end)
    local sample={unit_id=u.id,soul_available=soul~=nil,unavailable=out.unavailable,truncated=out.truncated,
        attributes={physical=read('attributes.physical',function()
            return attributes(u.body.physical_attrs,'physical_attribute_type',nil,'attributes.physical') end)}}
    if soul then
        sample.soul_id=read('soul_id',function() return soul.id end)
        sample.attributes.mental=read('attributes.mental',function()
            return attributes(soul.mental_attrs,'mental_attribute_type',nil,'attributes.mental') end)
        sample.skills=read('skills',function() return skills(soul) end)
    else
        unavailable('skills','The character has no readable current soul')
        unavailable('attributes.mental','The character has no readable current soul')
    end
    return sample
end

local caste=read(brief and 'physiology.caste' or 'identity.caste',function() return dfhack.units.getCasteRaw(u) end)
out.identity=fields(u,{'hist_figure_id','race','caste','sex','birth_year','birth_time','custom_profession'},'identity')
out.identity.english_name=read('identity.english_name',function() return translated(u.name) end)
out.identity.age_years=read('identity.age_years',function() return dfhack.units.getAge(u) end)
if not brief then out.identity.sex_label=({[-1]='sexless',[0]='female',[1]='male'})[u.sex] or 'unknown' end
out.identity.race_token=read('identity.race_token',function() return dfhack.units.getRaceName(u) end)
if not brief then out.identity.caste_token=caste and text(caste.caste_id) or nil end
out.identity.profession=read('identity.profession',function() return text(dfhack.units.getProfessionName(u)) end)
out.identity.profession_id=read('identity.profession_id',function() return dfhack.units.getProfession(u) end)
out.identity.kill_count=read('identity.kill_count',function() return dfhack.units.getKillCount(u) end)
out.affiliation=read('affiliation',function()
    local result={civilization=named_reference('historical_entity',u.civ_id,'affiliation.civilization'),
        cultural_identity_id=u.cultural_identity,
        squad=named_reference('squad',u.military.squad_id,'affiliation.squad'),
        squad_position=u.military.squad_position}
    return result
end)

-- Keep the same health counters and inventory schema as ordinary observations,
-- and add the counters and explicit flags needed for a detailed status check.
local health=fields(u.counters,{'pain','nausea','dizziness','stunned','unconscious','suffocation','webbed','winded'},'health')
for key,value in pairs(fields(u.counters2,{'exhaustion','fever','numbness','paralysis',
        'hunger_timer','thirst_timer','sleepiness_timer','stomach_content','stomach_food','stored_fat'},'health')) do
    health[key]=value
end
for key,value in pairs(fields(u.body,{'blood_count','blood_max','infection_level'},'health')) do health[key]=value end
health.wounds=read('health.wounds',function() return #u.body.wounds end)
health.recuperation_healing_rate=read('health.recuperation_healing_rate',function() return u.effective_rate end)
health.flags=object()
for _,group in ipairs({{'flags1','on_ground','caged','chained','drowning','ridden','rider'},
        {'flags2','killed','swimming','breathing_good','breathing_problem','vision_good','vision_damaged','vision_missing'},
        {'flags3','ghostly','diving','floundering','on_crutch','body_temp_in_range','adv_yield','emotionally_overloaded'}}) do
    for index=2,#group do
        local name=group[index]
        health.flags[name]=read('health.flags.'..name,function() return u[group[1]][name] end)
    end
end
out.health=health

local function part_name(id)
    local part=u.body.body_plan.body_parts[id]
    return part and text(part.name_singular[0]) or nil
end

-- DF massst stores kilograms plus milligrams. A container's valid native
-- cache includes its contents. Never force calculateWeight in a read query.
local function mass_mg(weight, computed)
    if computed~=true then return nil,'Native weight cache is invalid or unavailable' end
    local whole,fraction=weight and weight.whole,weight and weight.fraction
    if type(whole)~='number' or type(fraction)~='number' or whole<0 or
            fraction<0 or fraction>=1000000 or whole~=math.floor(whole) or fraction~=math.floor(fraction) then
        return nil,'Native mass is missing or invalid'
    end
    return whole*1000000+fraction
end

local function inventory_weights(items)
    for _,item in ipairs(items or {}) do
        if item.capacity_unavailable then
            unavailable('inventory['..item.id..'].capacity_volume_raw',item.capacity_unavailable)
        end
        if item.contaminants_unavailable then
            unavailable('inventory['..item.id..'].contaminants',item.contaminants_unavailable)
        end
        if item.contaminants_truncated then
            out.truncated[#out.truncated+1]={path='inventory['..item.id..'].contaminants',
                total=item.contaminants_total,limit=128}
        end
        local mass,reason=mass_mg(item.weight_raw,item.weight_computed)
        if mass then item.weight_kg=mass/1000000 else item.weight_unavailable_reason=reason end
        inventory_weights(item.contents)
    end
end
inventory_weights(out.inventory)

-- A parent can retain its valid flag while a just-filled/melted child is
-- invalid. Its cached aggregate still drives native HUD load, but cannot prove
-- physical mass. Validate descendants without refreshing any native cache.
local function cache_tree(item,budget,seen,depth)
    if depth>16 then budget.depth_exceeded=true;error('Contained weight scan exceeds depth 16',0) end
    if budget.remaining<=0 then budget.exceeded=true;error('Contained weight scan exceeds 4096 items',0) end
    local id=item.id
    if seen[id] then error('Repeated or cyclic contained item '..tostring(id),0) end
    seen[id]=true;budget.remaining=budget.remaining-1
    local mass,reason=mass_mg(item.weight,item.flags.weight_computed)
    if not mass then error(('Item %s: %s'):format(id,reason or 'Unknown cached mass'),0) end
    local contents_mass=0
    for _,child in ipairs(dfhack.items.getContainedItems(item)) do
        contents_mass=contents_mass+cache_tree(child,budget,seen,depth+1)
    end
    if mass<contents_mass then error('Item '..tostring(id)..': cached mass is less than contained mass',0) end
    return mass
end

for _,item in ipairs(brief and {} or out.inventory or {}) do
    if item.body_part_id and item.body_part_id>=0 then
        item.body_part_name=read('inventory['..item.id..'].body_part_name',function() return part_name(item.body_part_id) end)
    end
end

out.encumbrance=read('encumbrance',function()
    local result={weight_complete=true,inventory_entry_count=#u.inventory,root_item_count=0,weighed_root_item_count=0,
        unweighed_root_item_count=0,heaviest_items=array(),by_mode=array(),unweighed_items=array(),
        source='Native cached mass; totals require valid root and descendant caches, with contents included once',
        heaviest_items_limit=10}
    local total,seen,by_mode,weighted=0,{},{},{}
    local cached_total,cached_complete=0,true
    local tree_budget,tree_seen={remaining=4096},{}
    local limit=4096
    if #u.inventory>limit then
        result.weight_complete=false;cached_complete=false
        out.truncated[#out.truncated+1]={path='encumbrance.inventory_scan',total=#u.inventory,limit=limit}
    end
    for index=0,math.min(#u.inventory,limit)-1 do
        local ok,entry,mass,reason,item=pcall(function()
            local inv=u.inventory[index]
            local item=inv.item
            local mg,why=mass_mg(item.weight,item.flags.weight_computed)
            return {id=item.id,description=text(dfhack.items.getReadableDescription(item)),
                mode=label('inv_item_role_type',inv.mode)},mg,why,item
        end)
        if not ok then reason=tostring(entry):sub(1,240);entry={inventory_index=index} end
        if not entry.id or not seen[entry.id] then
            if entry.id then seen[entry.id]=true end
            if ok and mass then
                cached_total=cached_total+mass
                local valid,why=pcall(cache_tree,item,tree_budget,tree_seen,0)
                if not valid then mass=nil;reason=tostring(why):sub(1,240) end
            else cached_complete=false end
            result.root_item_count=result.root_item_count+1
            local mode=entry.mode or 'unknown'
            local group=by_mode[mode] or {mode=mode,item_count=0,known_mass=0,weight_complete=true}
            by_mode[mode]=group;group.item_count=group.item_count+1
            if ok and mass then
                total=total+mass;group.known_mass=group.known_mass+mass
                result.weighed_root_item_count=result.weighed_root_item_count+1
                entry.weight_kg=mass/1000000
                weighted[#weighted+1]=entry
            else
                result.weight_complete=false;group.weight_complete=false
                result.unweighed_root_item_count=result.unweighed_root_item_count+1
                entry.reason=reason
                if #result.unweighed_items<100 then result.unweighed_items[#result.unweighed_items+1]=entry end
            end
        end
    end
    if cached_complete then result.native_cached_weight_kg=cached_total/1000000 end
    if tree_budget.exceeded then
        out.truncated[#out.truncated+1]={path='encumbrance.contained_weight_scan',limit=4096,scanned=4096}
    end
    if tree_budget.depth_exceeded then
        out.truncated[#out.truncated+1]={path='encumbrance.contained_weight_depth',limit=16}
    end
    result.known_weight_kg=total/1000000
    if result.weight_complete then result.total_weight_kg=result.known_weight_kg
    else unavailable('encumbrance.total_weight_kg','Carried root or descendant weight caches are invalid, inconsistent, unreadable or bounded') end
    for _,group in pairs(by_mode) do
        group.known_weight_kg=group.known_mass/1000000;group.known_mass=nil
        if #u.inventory>limit then group.weight_complete=false end
        if group.weight_complete then group.weight_kg=group.known_weight_kg end
        result.by_mode[#result.by_mode+1]=group
    end
    table.sort(result.by_mode,function(a,b) return a.mode<b.mode end)
    table.sort(weighted,function(a,b)
        if a.weight_kg==b.weight_kg then return a.id<b.id end
        return a.weight_kg>b.weight_kg
    end)
    for i=1,math.min(#weighted,result.heaviest_items_limit) do result.heaviest_items[#result.heaviest_items+1]=weighted[i] end
    if result.unweighed_root_item_count>100 then
        out.truncated[#out.truncated+1]={path='encumbrance.unweighed_items',total=result.unweighed_root_item_count,limit=100}
    end
    if not helpers.burden then
        for _,name in ipairs({'capacity','load_penalty','burden'}) do
            result[name]={available=false,reason='DFHack burden helper was not supplied'}
            unavailable('encumbrance.'..name,result[name].reason)
        end
    end
    return result
end)

out.body=object()
out.body.size_raw=read('body.size_raw',function()
    return fields(u.body.size_info,{'size_cur','size_base','area_cur','area_base','length_cur','length_base'},'body.size_raw')
end)
out.body.functional_parts=read('body.functional_parts',function()
    return fields(u.status2,{'limbs_stand_count','limbs_stand_max','limbs_grasp_count','limbs_grasp_max',
        'limbs_fly_count','limbs_fly_max'},'body.functional_parts')
end)
out.body.parts=read('body.parts',function()
    return list(u.body.body_plan.body_parts,512,'body.parts',function(part,index)
        local result={id=index,name=text(part.name_singular[0]),token=text(part.token),parent_id=part.con_part_id}
        result.active_status_flags=read('body.parts['..index..'].active_status_flags',function()
            return flags(u.body.components.body_part_status[index])
        end)
        return result
    end)
end)
out.body.wounds=read('body.wounds',function()
    return list(u.body.wounds,200,'body.wounds',function(wound,index)
        local path='body.wounds['..index..']'
        local result=fields(wound,{'id','age','attacker_unit_id','attacker_hist_figure_id','syndrome_id',
            'pain','nausea','dizziness','fever','paralysis','numbness'},path)
        result.flags=flags(wound.flags)
        result.parts=list(wound.parts,512,path..'.parts',function(layer,layer_index)
            local p=path..'.parts['..layer_index..']'
            local injury=fields(layer,{'body_part_id','layer_idx','global_layer_idx','bleeding','pain','nausea',
                'dizziness','paralysis','numbness','swelling','impaired','strain',
                'contact_area','surface_perc','max_penetration_perc','cur_penetration_perc'},p)
            if injury.body_part_id and injury.body_part_id>=0 then
                injury.body_part_name=read(p..'.body_part_name',function() return part_name(injury.body_part_id) end)
            end
            injury.flags1=flags(layer.flags1);injury.flags2=flags(layer.flags2)
            return injury
        end)
        return result
    end)
end)
out.body.syndromes=read('body.syndromes',function()
    return list(u.syndromes.active,100,'body.syndromes',function(syndrome,index)
        local path='body.syndromes['..index..']'
        local result=fields(syndrome,{'type','year','year_time','ticks','reinfection_count','wound_id'},path)
        result.flags=flags(syndrome.flags)
        local definition=read(path..'.definition',function() return df.syndrome.find(syndrome.type) end)
        result.name=read(path..'.name',function()
            return definition and text(definition.syn_name)
        end)
        result.identifier=definition and text(definition.syn_identifier) or nil
        result.symptoms=list(syndrome.symptoms,200,path..'.symptoms',function(symptom,symptom_index)
            local entry=fields(symptom,{'ticks','delay','quantity'},path..'.symptoms['..symptom_index..']')
            entry.index=symptom_index;entry.flags=flags(symptom.flags)
            entry.type=read(path..'.symptoms['..symptom_index..'].type',function()
                return definition and label('creature_interaction_effect_type',definition.ce[symptom_index]:getType())
            end)
            entry.targets=list(symptom.target_bp,512,path..'.symptoms['..symptom_index..'].targets',function(bp,i)
                return {body_part_id=bp,layer=symptom.target_layer[i],quantity=symptom.target_quantity[i],
                    ticks=symptom.target_ticks[i],delay=symptom.target_delay[i]}
            end)
            return entry
        end)
        return result
    end)
end)

out.attributes=object()
out.attributes.physical=read('attributes.physical',function()
    return attributes(u.body.physical_attrs,'physical_attribute_type',dfhack.units.getPhysicalAttrValue,'attributes.physical')
end)
local soul=read('soul',function() return u.status.current_soul end)
out.soul_available=soul~=nil
out.needs={physical=fields(u.counters2,{'hunger_timer','thirst_timer','sleepiness_timer',
    'exhaustion','stomach_content','stomach_food'},'needs.physical')}
if soul then
    out.attributes.mental=read('attributes.mental',function()
        return attributes(soul.mental_attrs,'mental_attribute_type',dfhack.units.getMentalAttrValue,'attributes.mental')
    end)
    out.skills=read('skills',function() return skills(soul) end)
    if not brief then
    local p=soul.personality
    out.needs.focus=fields(p,{'current_focus','undistracted_focus'},'needs.focus')
    out.needs.psychological=read('needs.psychological',function()
        return list(p.needs,100,'needs.psychological',function(need,index)
            local entry=fields(need,{'id','need_level','focus_level','deity_id'},'needs.psychological['..index..']')
            entry.name=label('need_type',need.id)
            if need.deity_id>=0 then entry.deity=named_reference('historical_figure',need.deity_id,'needs.psychological['..index..'].deity') end
            return entry
        end)
    end)
    out.personality=fields(p,{'stress','longterm_stress','combat_hardened'},'personality')
    out.personality.stress_category=read('personality.stress_category',function() return dfhack.units.getStressCategory(u) end)
    out.personality.traits=read('personality.traits',function()
        local result=array()
        for id=0,df.personality_facet_type._last_item do
            result[#result+1]={id=id,name=label('personality_facet_type',id),value=p.traits[id]}
        end
        return result
    end)
    out.personality.values=read('personality.values',function()
        return list(p.values,100,'personality.values',function(value)
            return {id=value.type,name=label('value_type',value.type),strength=value.strength}
        end)
    end)
    out.personality.goals=read('personality.goals',function()
        return list(p.dreams,100,'personality.goals',function(goal,index)
            return {id=goal.local_id,type=label('goal_type',goal.type),flags=flags(goal.flags),
                name=read('personality.goals['..index..'].name',function() return text(dfhack.units.getGoalName(u,index)) end),
                achieved=read('personality.goals['..index..'].achieved',function() return dfhack.units.isGoalAchieved(u,index) end)}
        end)
    end)
    out.personality.emotions=read('personality.emotions',function()
        return list(p.emotions,100,'personality.emotions',function(emotion,index)
            local entry=fields(emotion,{'strength','severity','relative_strength','subthought','year','year_tick'},'personality.emotions['..index..']')
            entry.type=label('emotion_type',emotion.type);entry.thought=label('unit_thought_type',emotion.thought)
            entry.flags=flags(emotion.flags)
            return entry
        end,true)
    end)
    end
else
    for _,path in ipairs({'attributes.mental','skills','needs.focus','needs.psychological','personality'}) do
        unavailable(path,'The adventurer has no current soul')
    end
end

-- unit.effective_rate is heal_rate_recuperation, not a movement rate.
out.movement=object()
out.movement.gaits=read('movement.gaits',function()
    local result=array()
    for id=0,df.gait_type._last_item do
        local selected=u.status.command_gait_index[id]
        local entry={type=label('gait_type',id),selected_index=selected,current_index=u.enemy.gait_index[id]}
        if selected>=0 then
            entry.definition=read('movement.gaits['..id..'].definition',function()
                local gait=u.body.body_plan.gait_info[id][selected]
                local definition=fields(gait,{'full_speed','start_speed','buildup_time','energy_use','stealth_slows','turn_max'},
                    'movement.gaits['..id..'].definition')
                definition.name=text(df.global.world.raws.creatures.action_strings[gait.action_string_idx])
                definition.flags=flags(gait.flags)
                return definition
            end)
        end
        result[#result+1]=entry
    end
    return result
end)
if not helpers.calculations then
    unavailable('movement.effective_speed','Character calculation module was not supplied')
end
out.movement.displayed_speed=read('movement.displayed_speed',function()
    local ui,s=helpers.ui,helpers.status
    assert(ui and s and s.screen=='viewscreen_dungeonmodest' and s.adventure_menu=='Default' and
        s.ready_for_input and not s.modal and #(s.open_panels or {})==0,
        'Movement HUD is not readable in the current interface state')
    -- Match the bottom HUD pair, its native gait name, and aligned columns.
    -- Never interpret an arbitrary decimal in a menu or report as speed.
    local rows={}
    for _,row in ipairs(ui.rows) do rows[row.y]=row.text end
    local gait_indent,gait=(rows[ui.height-2] or ''):match('^(%s*)(.-)%s*$')
    local speed_indent,value=(rows[ui.height-1] or ''):match('^(%s*)(%d+%.%d+)%s*$')
    assert(value and gait_indent==speed_indent,'Movement HUD gait/speed pair is absent or unrecognized')
    local recognized=false
    for _,entry in ipairs(out.movement.gaits or {}) do
        if entry.definition and entry.definition.name==gait then recognized=true;break end
    end
    assert(recognized,'Movement HUD gait does not match a native selected gait')
    return {value=tonumber(value),text=value,gait=gait,source='ui_character_layer',units='native_display',
        gait_row=ui.height-2,value_row=ui.height-1,
        meaning='Rounded current HUD speed; not a capacity percentage or an isolated load penalty'}
end)
out.activity=read('activity',function()
    return {following_unit_id=u.following and u.following.id or nil,
        actions=list(u.actions,100,'activity.actions',function(action)
            return {id=action.id,type=label('unit_action_type',action.type)}
        end)}
end)
out.semantics={source='DFHack character state; read-only',
    counters='Native raw values; no invented hunger, fatigue, injury severity, or threat thresholds',
    attributes='value and max_value are stored attributes; effective includes DFHack attribute modifiers',
    skills='Native skill records; effective includes rust and current physical/mental penalties',
    stress_category='Native DFHack category: 0 is most stressed, 6 is least in this build',
    body_parts='All named parts; active_status_flags lists true native flags, including damage and treatment',
    physical_needs='Timers are raw counters; physiological requirements vary by creature',
    encumbrance='Total cached carried mass requires valid root and descendant caches, without skill discounts. Native cached root load is separate and may be stale after contents change. Unknown weight is not zero',
    units='weight_kg is kilograms (weight_raw.whole + fraction/1000000); body dimensions, wound counters, and gait parameters retain native units'}
if helpers.details_reader then
    return helpers.details_reader(u,out,{array=array,text=text,read=read,fields=fields,list=list,flags=flags,
        label=label,named_reference=named_reference,unavailable=unavailable,caste=caste,ui=helpers.ui,status=helpers.status,
        calculations=helpers.calculations,interfaces=helpers.interfaces,next_dawn=helpers.next_dawn,burden=helpers.burden,
        profile=helpers.profile,requested=requested})
end
return out

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
