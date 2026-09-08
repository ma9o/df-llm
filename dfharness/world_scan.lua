--@ module=true
--luacheck: globals factory
local function build(h)
-- Copy the bounded world site index once under DFHack's core lock. Filtering
-- can run outside the game; native pointers never enter parallel workers.
local M={}
local LIMIT=32768
local function int(value,label)
    assert(type(value)=='number' and value%1==0,label..' is unavailable')
    return value
end
local function names(enum)
    local out=h.array()
    local first,last=int(enum._first_item,'First enum ID'),int(enum._last_item,'Last enum ID')
    assert(last>=first and last-first<1024,'Native token catalog exceeds its bound')
    for id=first,last do
        local name=enum[id]
        if type(name)=='string' and name~='NONE' then
            out[#out+1]=name
        end
    end
    table.sort(out)
    return out
end
local subtypes={LairShrine='lair_type',Fortress='fortress_type',Monument='monument_type'}
local function record(site,flag_names,flag_error)
    local out={id=int(site.id,'Site ID'),type=df.world_site_type[site.type]}
    assert(out.id>=0 and type(out.type)=='string','Native site identity is unavailable')
    out.name=h.text(dfhack.translation.translateName(site.name,true))
    local native=h.text(dfhack.translation.translateName(site.name,false))
    if native~=out.name then out.native_name=native end
    local read,flags=pcall(function()
        assert(flag_names,flag_error or 'Native site flag catalog is unavailable')
        local active=h.array()
        for _,name in ipairs(flag_names)do
            local value=site.flag[name]
            assert(type(value)=='boolean','Native site flag '..name..' is unavailable')
            if value then active[#active+1]=name end
        end
        return active
    end)
    if read then out.flags=flags else out.flags_unavailable=tostring(flags):sub(1,180)end
    local x1,x2=int(site.global_min_x,'Site minimum x'),int(site.global_max_x,'Site maximum x')
    local y1,y2=int(site.global_min_y,'Site minimum y'),int(site.global_max_y,'Site maximum y')
    assert(x1>=0 and y1>=0 and x2>=x1 and y2>=y1,'Invalid native site bounds')
    out.bounds={x1=x1*3,y1=y1*3,x2=x2*3+2,y2=y2*3+2}
    out.position={x=math.floor((out.bounds.x1+out.bounds.x2)/2),
        y=math.floor((out.bounds.y1+out.bounds.y2)/2),z=0}
    local subtype=subtypes[out.type]
    if subtype then
        -- These fields share a structure, but only the tagged site's member is
        -- meaningful. Missing optional subtype_info differs from a failed read.
        local ok,err=pcall(function()
            local info=site.subtype_info
            out.subtype_present=info~=nil
            if info then
                out.subtype=df[subtype][info[subtype]]
                assert(type(out.subtype)=='string','Native site subtype is unavailable')
            end
        end)
        if not ok then out.subtype_unavailable=tostring(err):sub(1,180)end
    end
    return out
end
function M.snapshot(epoch,catalog_only,travel_position)
    local out={available=false,format='world_site_snapshot',schema_version=1,
        scope='World site records, not character knowledge or visibility; no biome or local-tile scan',
        coordinates='Surface travel tiles (16 local tiles); position is the site bounding-box center',
        sites=h.array(),errors=h.array(),error_count=0}
    local ok,err=pcall(function()
        if catalog_only then
            out.tokens={site=names(df.world_site_type)}
            out.complete=true
            for _,subtype in ipairs({'lair_type','fortress_type','monument_type','site_flag_type'})do
                local read,value=pcall(names,df[subtype])
                if read then out.tokens[subtype]=value
                else
                    out.complete=false
                    out.unavailable=out.unavailable or {}
                    out.unavailable[subtype]=tostring(value):sub(1,180)
                end
            end
            out.available=true;return
        end
        assert(dfhack.isWorldLoaded(),'No world is loaded')
        local world=df.global.world
        local sites=world.world_data.sites
        out.world={epoch=epoch,save=world.cur_savegame.save_dir,
            year=df.global.cur_year,year_tick=df.global.cur_year_tick}
        local origin_ok,origin=pcall(function()
            if not dfhack.isMapLoaded()then
                local p=travel_position and travel_position()
                if p then
                    return {x=int(p.x,'Travel x'),y=int(p.y,'Travel y')}
                end
                return
            end
            local unit=dfhack.world.getAdventurer()
            if not unit then return end
            local x,y=dfhack.units.getPosition(unit)
            int(x,'Adventurer x');int(y,'Adventurer y')
            return {x=math.floor((world.map.region_x*48+x)/16),
                y=math.floor((world.map.region_y*48+y)/16)}
        end)
        if origin_ok then out.origin=origin else out.origin_unavailable=tostring(origin):sub(1,180)end
        out.total=#sites;out.scanned=math.min(out.total,LIMIT)
        local flag_ok,flag_names=pcall(names,df.site_flag_type)
        for i=0,out.scanned-1 do
            local read,value=pcall(function()
                return record(sites[i],flag_ok and flag_names or nil,not flag_ok and tostring(flag_names) or nil)
            end)
            if read then out.sites[#out.sites+1]=value
            else
                out.error_count=out.error_count+1
                if #out.errors<20 then out.errors[#out.errors+1]={index=i,reason=tostring(value):sub(1,180)}end
            end
        end
        out.truncated=out.scanned<out.total
        out.complete=not out.truncated and out.error_count==0
        out.available=true
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
