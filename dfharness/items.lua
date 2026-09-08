--@ module=true
--luacheck: globals factory
local function build(...)
-- Native storage and coating properties, bounded and read-only.
local h=...
local M={}
local array,text,optional,copy=h.array,h.text,h.optional,h.copy
function M.info(item,depth,budget,location,seen)
    depth=depth or 0; budget=budget or {remaining=300}; seen=seen or {}
    budget.remaining=budget.remaining-1
    local quality=item:getQuality()
    local out={id=item.id,description=text(dfhack.items.getReadableDescription(item)),
        quality=quality,wear=optional(function() return item:getWear() end),
        weight_raw=optional(function() return {whole=item.weight.whole,fraction=item.weight.fraction} end),
        weight_computed=optional(function() return item.flags.weight_computed end),location=location}
    for k,v in pairs(M.storage(item))do out[k]=v end
    if budget.brief then
        local children=dfhack.items.getContainedItems(item)
        if #children>0 or (out.capacity_volume_raw or 0)>0 then out.contents_shown_in_full_view=#children end
        return out
    end
    out.type=df.item_type[item:getType()];out.stack_size=item:getStackSize()
    out.material_ref=optional(function()
        local m=dfhack.matinfo.decode(item);return {type=m.type,index=m.index,token=m:getToken()}
    end)
    if not budget.catalog then
        out.subtype=item:getSubtype()
        out.material=optional(function() return text(dfhack.matinfo.decode(item):toString()) end)
        out.temperature=optional(function()return {whole=item.temperature.whole,fraction=item.temperature.fraction}end)
        out.volume_raw=optional(function() return item:getVolume() end)
    end
    local maker=optional(function() return item:getMakerRace() end)
    if maker and maker>=0 then
        out.fit={maker_race_id=maker,maker_species=optional(function() return text(df.global.world.raws.creatures.all[maker].name[0]) end),
            wearable_now='unknown'}
    end
    local def=dfhack.items.getSubtypeDef(item:getType(),item:getSubtype())
    if def then
        if not budget.catalog then out.definition={id=def.id,name=text(def.name)} end
        out.armor=optional(function() return {coverage=def.props.coverage,layer=def.props.layer,
            layer_size=def.props.layer_size,layer_permit=def.props.layer_permit} end)
        if out.armor then
            out.armor.layer_name=optional(function()return df.clothing_layer_type[def.props.layer]end)
            out.armor.shaped=optional(function()
                local value=def.props.flags[df.armor_general_flags.SHAPED]
                assert(type(value)=='boolean','Unknown SHAPED flag')
                return value
            end)
            if out.armor.shaped==nil then out.armor.shaped_unavailable='Native SHAPED flag unavailable' end
        end
        if not budget.catalog and item:getType()==df.item_type.WEAPON then
            out.weapon={skill=df.job_skill[def.skill_melee],minimum_size=def.minimum_size,
                two_handed_size=def.two_handed,attacks=array()}
            for index,a in ipairs(def.attacks) do
                out.weapon.attacks[#out.weapon.attacks+1]={attack_index=index,verb=text(a.verb_2nd),edged=a.edged,
                    contact=a.contact,penetration=a.penetration,velocity_mult=a.velocity_mult}
            end
        end
    end
    if seen[item.id] then out.contents_truncated=true; return out end
    seen[item.id]=true
    local children=dfhack.items.getContainedItems(item)
    -- A successfully read empty container is distinct from missing contents.
    -- Preserve the empty list for container postconditions and character state.
    if #children>0 or (out.capacity_volume_raw or 0)>0 then
        out.contents=array()
        for _,child in ipairs(children) do
            if depth>=(budget.max_depth or 4) or budget.remaining<=0 then
                out.contents_truncated=true;out.contents_total=#children;break
            end
            if budget.include_hidden or not child.flags.hidden then
                local child_location=copy(location or {});child_location.container_id=item.id
                child_location.mode=nil;child_location.body_part_id=nil
                out.contents[#out.contents+1]=M.info(child,depth+1,budget,child_location,seen)
            else
                out.contents_truncated=true;out.contents_total=#children
            end
        end
    end
    return out
end

-- Furniture stock is absent from map_block.items and can have both on_ground
-- and in_building unset. The holder's tagged TEMP records are authoritative.
function M.building_contents(b,limit,item_type)
    local out={available=false,source='building_actual.contained_items',entries=h.array(),
        counts={},matched=0,item_count=0,scanned=0,omitted_permanent=0,omitted_hidden=0}
    local ok,err=pcall(function()
        assert(b and df.building_actual:is_instance(b),'Building has no native item storage')
        assert(dfhack.maps.isTileVisible(b.centerx,b.centery,b.z),'Building is not visible')
        if item_type then assert(type(df.item_type[item_type])=='number','Unknown native item type')end
        out.building_id=b.id;out.total_records=#b.contained_items
        for _,record in ipairs(b.contained_items)do
            if out.scanned>=4096 then out.scan_truncated=true;break end
            out.scanned=out.scanned+1
            local role=df.building_item_role_type[record.use_mode]
            assert(role=='TEMP' or role=='PERM' or role=='TEMP_PRINTHIDDEN','Unknown building item role')
            if role=='PERM' then out.omitted_permanent=out.omitted_permanent+1
            elseif role=='TEMP_PRINTHIDDEN' then out.omitted_hidden=out.omitted_hidden+1
            else
                local item=record.item
                assert(item and type(item.flags.hidden)=='boolean','Native stored item is unavailable')
                local x,y,z=dfhack.items.getPosition(item)
                assert(type(x)=='number' and type(y)=='number' and type(z)=='number','Stored item position is unavailable')
                if item.flags.hidden or not dfhack.maps.isTileVisible(x,y,z) then
                    out.omitted_hidden=out.omitted_hidden+1
                else
                    local kind=df.item_type[item:getType()]
                    assert(type(kind)=='string','Unknown native stored item type')
                    out.item_count=out.item_count+1;out.counts[kind]=(out.counts[kind] or 0)+1
                    if not item_type or kind==item_type then
                        out.matched=out.matched+1
                        if #out.entries<limit then
                            out.entries[#out.entries+1]={id=item.id,type=kind,
                                location={kind='building',building_id=b.id,root_item_id=item.id,
                                    position={x=x,y=y,z=z}}}
                        end
                    end
                end
            end
        end
        out.truncated=out.scan_truncated==true or #out.entries<out.matched
        out.available=true
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
function M.building_location(root)
    local b=dfhack.items.getHolderBuilding(root)
    if not b then return end
    local contents=M.building_contents(b,4096)
    if contents.available then
        for _,entry in ipairs(contents.entries)do
            if entry.id==root.id then return entry.location end
        end
    end
end
function M.option(o,kind,verified)
    if kind~='DROP_ITEM' then return {} end
    local out={}
    local ok,err=pcall(function()
        assert(df.adventure_option_drop_itemst:is_instance(o),'Unknown native drop option class')
        assert(type(o.depth)=='number','Native inventory depth is unavailable')
        local liquid=o.item:isLiquid()
        assert(type(liquid)=='boolean','Native item liquid flag is unavailable')
        if o.depth>0 and liquid then
            -- Native DROP handler 0x894b93 checks depth and isLiquid, then
            -- empties the owning container instead of dropping this one item.
            assert(verified,'Contained-liquid drop semantics are unverified for this build')
            local container=dfhack.items.getContainer(o.item)
            assert(container and type(container.id)=='number','Liquid container is unavailable')
            out.operation='empty_container';out.container_id=container.id
        else out.operation='drop_item' end
    end)
    if not ok then out.details_unavailable=tostring(err):sub(1,240) end
    return out
end
function M.storage(item)
    local out={}
    local ok,capacity=pcall(dfhack.items.getCapacity,item)
    if ok and type(capacity)=='number' and capacity>=0 and capacity==math.floor(capacity) then
        out.capacity_volume_raw=capacity
    else out.capacity_unavailable=ok and 'Invalid native capacity' or tostring(capacity):sub(1,240) end
    local read,coatings=pcall(function()
        local list=item.contaminants
        local result=h.array()
        if not list then return result end
        for index,c in ipairs(list) do
            if #result>=128 then out.contaminants_truncated=true;out.contaminants_total=#list;break end
            local b=c.base
            local material=dfhack.matinfo.decode(b.mat_type,b.mat_index)
            assert(material,'Unknown coating material at '..index)
            result[#result+1]={material=material:getToken(),state=df.matter_state[b.mat_state],
                size=b.size,temperature={whole=b.temperature.whole,fraction=b.temperature.fraction},
                body_part_id=c.body_part_id,external=c.flags.external,evaporates=b.base_flags.evaporates}
        end
        return result
    end)
    if read then out.contaminants=coatings
    else out.contaminants_unavailable=tostring(coatings):sub(1,240) end
    return out
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
