--@ module=true
--luacheck: globals factory
local function build(...)
-- Native movement settings. Enumerate creature gaits, never hardcode species.
local h=...
local M={}
-- Shared visibility scope for full input guards and narrow processing watches.
-- Only the full reader requests names/positions; progress needs identities.
function M.visible_units(loaded,project)
    local out={units=h.array(),units_available=true,units_truncated=false}
    if not loaded then return out end -- No locally loaded units is a known set.
    local ok,err=pcall(function()
        local scanned=0
        for _,unit in ipairs(df.global.world.units.active)do
            if scanned>=32768 then out.units_truncated=true;break end
            scanned=scanned+1
            if dfhack.units.isVisible(unit) and not dfhack.units.isHidden(unit) then
                if #out.units>=500 then out.units_truncated=true;break end
                local id=unit.id
                assert(type(id)=='number' and id>=0 and id<=2147483647 and id==math.floor(id),
                    'Native visible unit identity is unavailable')
                out.units[#out.units+1]=project and project(unit) or {id=id}
            end
        end
    end)
    if not ok then out.units_available=false;out.units_unavailable=tostring(err):sub(1,180) end
    return out
end
function M.route_window(size,start,target,width,height)
    local function axis(n,a,b,minimum,maximum)
        local length=math.min(n,maximum,math.max(minimum,math.abs(a-b)+11))
        local first=math.max(0,math.min(n-length,math.floor((a+b-length)/2)))
        -- At the technical size bound, keep the character in the crop. A
        -- distant destination remains explicitly outside it; never guess terrain.
        local margin=math.min(5,length//2)
        first=math.max(0,math.min(n-length,math.max(a-length+1+margin,math.min(a-margin,first))))
        return first,length
    end
    local x,w=axis(size.x,start.x,target.x,width,101)
    local y,height_out=axis(size.y,start.y,target.y,height,61)
    return {origin={x=x,y=y,z=start.z},width=w,height=height_out,
        target_included=target.z==start.z and target.x>=x and target.x<x+w
            and target.y>=y and target.y<y+height_out}
end
function M.map_units(units,origin,width,height,adventurer_id)
    local result=h.array()
    for _,u in ipairs(units) do
        local info={};for k,v in pairs(u)do info[k]=v end
        local p=u.position
        info.in_map=p~=nil and p.z==origin.z and p.x>=origin.x and p.x<origin.x+width
            and p.y>=origin.y and p.y<origin.y+height or false
        info.glyph=u.id==adventurer_id and '@' or 'u'
        result[#result+1]=info
    end
    return result
end
local function read(fn)
    local ok,v=pcall(fn)
    return ok and v or nil
end
function M.character(u)
    local out={available=true}
    local ok,err=pcall(function()
        out.sneaking=u.flags1.hidden_in_ambush
        assert(type(out.sneaking)=='boolean','Sneaking flag is unavailable')
        out.selected_gaits={}
        for i=0,df.gait_type._last_item do
            local selected=u.status.command_gait_index[i]
            assert(type(selected)=='number','Gait selection is unavailable')
            out.selected_gaits[df.gait_type[i]]=selected
        end
    end)
    if not ok then out.available=false;out.reason=tostring(err):sub(1,240) end
    return out
end
function M.menu(_)
    local a=df.global.game.main_interface.adventure.movement_options
    if not a.open then return nil end
    local out={kind='movement',open=true,options=h.array()}
    local ok,err=pcall(function()
        local u=a.speed_sneak_un
        assert(u,'Movement menu target is unavailable')
        out.unit_id=u.id;out.gait_type=df.gait_type[a.gait_type];out.scroll=a.scroll_gait
        out.scrolling=a.scrolling_gait
        if out.scrolling then out.selection_unavailable='Finish dragging the gait scroll bar before selection' end
        out.selected_index=u.status.command_gait_index[a.gait_type]
        local list=u.body.body_plan.gait_info[a.gait_type]
        out.total=#list
        for index,g in ipairs(list) do
            if #out.options>=500 then out.truncated=true;break end
            local name=h.text(df.global.world.raws.creatures.action_strings[g.action_string_idx])
            local entry={id=('gait:%d:%s:%d:%d'):format(u.id,out.gait_type,index,g.action_string_idx),
                index=index,kind='gait',label=name,gait_type=out.gait_type,gait_index=index,
                unit_id=u.id}
            out.options[#out.options+1]=h.bindings.bind(entry,index,out.scroll,h.bindings.list_supported(out))
        end
        -- The shared adapter probes native scroll bounds, including the small
        -- single-page case where DF ignores a stale stored offset.
    end)
    if not ok then out.selection_unavailable=tostring(err):sub(1,240) end
    return h.bindings.catalog(out)
end
-- Expose only the read needed by execution; optional panels may disappear on
-- updates and must not make the ordinary character observation fail.
function M.open()
    return read(function()return df.global.game.main_interface.adventure.movement_options.open end)==true
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
