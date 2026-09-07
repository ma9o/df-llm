--@ module=true
--luacheck: globals factory
local function build(...)
-- Bounded read-only inspection of a currently visible character. No risk score.
local u,out,h=...
local array=h.array
local function text(v)
    if v~=nil and type(v)~='string' then v=v.value end
    return h.text(v)
end
out.unavailable=array();out.truncated=array()
local function read(path,fn)
    local ok,v=pcall(fn)
    if ok and v~=nil then return v end
    out.unavailable[#out.unavailable+1]={path=path,reason=ok and 'Not available' or tostring(v):sub(1,180)}
end
local function list(path,values,limit,convert)
    local result=array()
    if #values>limit then out.truncated[#out.truncated+1]={path=path,total=#values,limit=limit} end
    for i=0,math.min(#values,limit)-1 do
        local value=read(path..'['..i..']',function()return convert(values[i],i)end)
        if value~=nil then result[#result+1]=value end
    end
    return result
end
local function fields(path,obj,names)
    local result={}
    for _,name in ipairs(names) do result[name]=read(path..'.'..name,function()return obj[name]end) end
    return result
end
out.identity=read('identity',function()
    return {hist_figure_id=u.hist_figure_id,sex=u.sex,age_years=dfhack.units.getAge(u),
        profession=text(dfhack.units.getProfessionName(u)),civilization_id=u.civ_id}
end)
out.health=fields('health',u.body,{'blood_count','blood_max'})
for _,name in ipairs({'pain','nausea','unconscious','stunned','suffocation','winded'}) do
    out.health[name]=read('health.'..name,function()return u.counters[name]end)
end
out.health.exhaustion=read('health.exhaustion',function()return u.counters2.exhaustion end)
out.health.wounds=read('health.wounds',function()return #u.body.wounds end)
out.attributes={}
out.attributes.physical=read('attributes.physical',function()
    local values=array()
    for id=df.physical_attribute_type._first_item,df.physical_attribute_type._last_item do
        local a=u.body.physical_attrs[id]
        values[#values+1]={id=id,name=df.physical_attribute_type[id],value=a.value,
            effective=dfhack.units.getPhysicalAttrValue(u,id)}
    end
    return values
end)
out.skills=read('skills',function()
    local soul=u.status.current_soul
    if not soul then return {present=false} end
    return list('skills',soul.skills,300,function(skill)
        return {id=skill.id,name=df.job_skill[skill.id],caption=text(df.job_skill.attrs[skill.id].caption),
            rating=skill.rating,rating_name=text(df.skill_rating.attrs[skill.rating].caption),
            effective=dfhack.units.getEffectiveSkill(u,skill.id),experience=skill.experience}
    end)
end)
out.body=read('body',function()
    return {size=fields('body.size',u.body.size_info,{'size_cur','size_base'}),
        parts=list('body.parts',u.body.body_plan.body_parts,512,function(part,id)
            local flags=array()
            for name,v in pairs(u.body.components.body_part_status[id]) do if v==true then flags[#flags+1]=name end end
            table.sort(flags)
            return {id=id,name=text(part.name_singular[0]),active_status_flags=flags}
        end)}
end)
out.combat=read('combat',function()
    return {opponent_unit_id=u.opponent.unit_id,
        last_hit=fields('combat.last_hit',u.last_hit,{'item','item_type','item_subtype','mattype','matindex'}),
        note='Native opponent reference; no hostility inference or win probability'}
end)
if out.combat then
    out.combat.creature_flags=h.health.creature_flags(u)
    for name,reason in pairs(out.combat.creature_flags.unavailable or {})do
        out.unavailable[#out.unavailable+1]={path='combat.creature_flags.'..name,reason=reason}
    end
end
out.condition=h.health.combat_condition(u)
for name,reason in pairs(out.condition.unavailable or {})do
    out.unavailable[#out.unavailable+1]={path='condition.'..name,reason=reason}
end
for _,name in ipairs({'parts','grapples'})do
    if out.condition[name..'_omitted'] then
        out.truncated[#out.truncated+1]={path='condition.'..name,omitted=out.condition[name..'_omitted']}
    end
end
out.affiliations=read('affiliations',function()
    local hf=df.historical_figure.find(u.hist_figure_id)
    if not hf then return {present=false} end
    return list('affiliations',hf.entity_links,100,function(link)
        local entity=df.historical_entity.find(link.entity_id)
        return {entity_id=link.entity_id,type=df.histfig_entity_link_type[link:getType()],
            name=entity and text(dfhack.translation.translateName(entity.name,true)) or nil}
    end)
end)
out.semantics={source='Visible unit native state; read-only; not limited to information shown on the premium UI',
    inventory='Native inventory roles; nested items retain explicit bounds',
    skills='Stored records and effective ratings; absent skill records are not fabricated',
    assessment='The controller assesses threats and chooses targets'}
if out.inventory_truncated then out.truncated[#out.truncated+1]={path='inventory',reason='Native inventory scan reached its item bound'} end
local function inventory_bounds(items)
    for _,item in ipairs(items) do
        if item.contents_truncated then out.truncated[#out.truncated+1]={path='inventory['..item.id..'].contents',total=item.contents_total} end
        if item.contents then inventory_bounds(item.contents) end
    end
end
inventory_bounds(out.inventory or {})
out.coverage={complete=#out.unavailable==0 and #out.truncated==0 and not out.inventory_truncated,
    unavailable_count=#out.unavailable,truncated_count=#out.truncated,sections=array()}
for _,name in ipairs({'identity','health','attributes','skills','inventory','body','combat','condition','affiliations'}) do
    local partial=false
    for _,v in ipairs(out.unavailable) do if v.path:match('^'..name..'[%.%[]') or v.path==name then partial=true end end
    for _,v in ipairs(out.truncated) do if v.path:match('^'..name..'[%.%[]') or v.path==name then partial=true end end
    out.coverage.sections[#out.coverage.sections+1]={section=name,
        status=out[name]==nil and 'unavailable' or partial and 'partial' or 'available'}
end
return out

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
