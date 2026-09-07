--@ module=true
--luacheck: globals factory
local function build(...)
-- Native storage and coating properties, bounded and read-only.
local h=...
local M={}
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
