--@ module=true
--luacheck: globals factory
local function build(...)
-- Structured visible terrain/buildings. No movement or hidden-tile queries.
local h=...
local M={}
function M.option(o)
    local out={}
    local function instance(name)
        local ok,v=pcall(function()return df[name]:is_instance(o)end)
        return ok and v
    end
    local function coord(p)return {x=p.x,y=p.y,z=p.z}end
    local function material(kind,index,state)
        local m=dfhack.matinfo.decode(kind,index)
        assert(m,'Native source material could not be decoded')
        local phase=df.matter_state[state]
        assert(type(phase)=='string','Native source phase is unavailable')
        return {type=kind,index=index,state=phase,token=m:getToken()}
    end
    local ok,err=pcall(function()
        if instance('adventure_environment_optionst') then
            out.target_position=coord(o.target_pos);out.player_position=coord(o.player_pos)
        end
        if instance('adventure_environment_pickup_make_campfirest') then out.operation='make_campfire'
        elseif instance('adventure_environment_ingest_materialst') then
            -- Read the tagged fields only. getIngestedItem() creates a native
            -- item and must never be called by an observation.
            out.operation='ingest_material'
            out.material_ref=material(o.mat_type,o.mat_index,o.mat_state)
        elseif instance('adventure_item_interact_heat_from_tilest') then
            out.operation='heat_item';out.item_id=o.item.id
            out.player_position=coord(o.pos1);out.target_position=coord(o.pos2)
        elseif instance('adventure_item_interact_fill_with_materialst') then
            out.operation='fill_container';out.container_id=o.container.id
            out.player_position=coord(o.pos1);out.target_position=coord(o.pos2)
            out.material_ref=material(o.material,o.matgloss,o.state)
        elseif instance('adventure_item_interact_fill_from_containerst') then
            out.operation='fill_container';out.container_id=o.container.id;out.source_container_id=o.take_from.id
            out.player_position=coord(o.pos1);out.target_position=coord(o.pos2)
        elseif instance('adventure_environment_place_on_pack_animalst') then
            out.operation='pack';out.item_id=o.item.id;out.pack_animal_id=o.pack_animal.id
        elseif instance('adventure_environment_take_from_pack_animalst') then
            out.operation='unpack';out.item_id=o.item.id;out.pack_animal_id=o.pack_animal.id
        end
    end)
    if not ok then out.details_unavailable=tostring(err):sub(1,240) end
    return out
end
function M.building(b)
    local out={id=b.id,unavailable=h.array()}
    local function read(name,fn)
        local ok,v=pcall(fn)
        if ok and v~=nil then out[name]=v
        else out.unavailable[#out.unavailable+1]=name end
    end
    read('type',function()return df.building_type[b:getType()] or tostring(b:getType())end)
    read('position',function()return {x=b.centerx,y=b.centery,z=b.z}end)
    read('bounds',function()return {x1=b.x1,y1=b.y1,x2=b.x2,y2=b.y2}end)
    local function flags(source,names)
        local values={}
        for _,name in ipairs(names) do
            assert(type(source[name])=='boolean','Unknown building flag type')
            values[name]=source[name]
        end
        return values
    end
    -- Tagged derived classes only. Do not infer water availability from the
    -- existence of a well, or read unrelated union/class payloads.
    if out.type=='Well' then
        read('well',function()
            assert(df.building_wellst:is_instance(b))
            return {bucket_z=b.bucket_z,flags=flags(b.well_flags,{'lowering','just_raised'}),
                water_availability='Requires a native interaction; not inferred from the well'}
        end)
    elseif out.type=='Door' or out.type=='Hatch' then
        read('door',function()
            local class=out.type=='Door' and df.building_doorst or df.building_hatchst
            assert(class:is_instance(b))
            return flags(b.door_flags,{'closed','forbidden','operated_by_mechanisms'})
        end)
    end
    if h.item_reader and df.building_actual:is_instance(b) then
        local storage=h.item_reader.building_contents(b,0)
        -- A scene needs the count, not every object on every table. The explicit
        -- items query filters native entries before reading detailed profiles.
        if not storage.available or storage.item_count>0 or storage.omitted_hidden>0 then
            storage.entries=nil;storage.matched=nil;storage.truncated=storage.scan_truncated==true
            out.storage=storage
        end
    end
    if #out.unavailable==0 then out.unavailable=nil end
    return out
end
function M.liquids(tiles,position)
    local remaining={}
    local function key(p)return p.x..':'..p.y end
    for _,t in ipairs(tiles) do remaining[key(t.position)]=t end
    local out=h.array()
    for _,seed in ipairs(tiles) do
        if remaining[key(seed.position)] then
            local p=seed.position
            local region={kind=seed.kind,tiles=0,depth_min=seed.depth,depth_max=seed.depth,
                bounds={x1=p.x,y1=p.y,x2=p.x,y2=p.y},nearest=p,distance=math.huge}
            local queue,index={seed},1
            remaining[key(p)]=nil
            while index<=#queue do
                local t=queue[index];index=index+1;p=t.position
                region.tiles=region.tiles+1
                region.depth_min=math.min(region.depth_min,t.depth)
                region.depth_max=math.max(region.depth_max,t.depth)
                local b=region.bounds
                b.x1=math.min(b.x1,p.x);b.y1=math.min(b.y1,p.y)
                b.x2=math.max(b.x2,p.x);b.y2=math.max(b.y2,p.y)
                local distance=math.max(math.abs(p.x-position.x),math.abs(p.y-position.y))
                if distance<region.distance then region.distance=distance;region.nearest=p end
                for _,delta in ipairs({{1,0},{-1,0},{0,1},{0,-1}}) do
                    local id=(p.x+delta[1])..':'..(p.y+delta[2])
                    local neighbor=remaining[id]
                    if neighbor and neighbor.kind==seed.kind then
                        remaining[id]=nil;queue[#queue+1]=neighbor
                    end
                end
            end
            out[#out+1]=region
        end
    end
    table.sort(out,function(a,b)
        if a.distance~=b.distance then return a.distance<b.distance end
        if a.nearest.y~=b.nearest.y then return a.nearest.y<b.nearest.y end
        return a.nearest.x<b.nearest.x
    end)
    return out
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
