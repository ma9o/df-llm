--@ module=true
--luacheck: globals factory
local function build(...)
-- Read-only adapters for maintained DFHack location and biome helpers.
local h=...
local M={}
local function coord(p)
    if not p then return end
    local out={}
    for _,k in ipairs({'x','y','z'})do
        local v=p[k]
        if v~=nil then
            assert(type(v)=='number' and v==math.floor(v),'Invalid native coordinate')
            out[k]=v
        end
    end
    assert(out.x and out.y,'Incomplete native coordinate')
    return out
end
function M.current_site(status)
    local meta={available=true,source='dfhack.world.getCurrentSite'}
    local ok,site=pcall(function()
        if status.map_loaded then return dfhack.world.getCurrentSite()end
        -- The shipped helper requires a loaded adventurer. During travel only,
        -- use native travel coordinates and site bounds; do not scan locally.
        meta.source='native_travel_site_bounds'
        local p=status.travel and status.travel.position
        assert(p,'No loaded adventurer or travel coordinate')
        for i,s in ipairs(df.global.world.world_data.sites)do
            assert(i<32768,'Site enumeration exceeded 32768 entries')
            if p.x>=s.global_min_x*3 and p.x<=s.global_max_x*3+2
                and p.y>=s.global_min_y*3 and p.y<=s.global_max_y*3+2 then return s end
        end
    end)
    if not ok then meta.available=false;meta.reason=tostring(site):sub(1,240);return nil,meta end
    meta.present=site~=nil
    return site,meta
end
function M.biome(position)
    local out={available=false,source='dfhack.maps.getTileBiomeRgn/getRegionBiome/getBiomeType'}
    local ok,err=pcall(function()
        assert(position and dfhack.isMapLoaded(),'No local map position is loaded')
        assert(dfhack.maps.isTileVisible(position.x,position.y,position.z),'Tile is not visible')
        local x,y=dfhack.maps.getTileBiomeRgn(position)
        assert(type(x)=='number' and type(y)=='number' and x>=0 and y>=0,'Native biome region is unavailable')
        out.region={x=x,y=y}
        local region=dfhack.maps.getRegionBiome(x,y)
        assert(region,'Native biome region entry is unavailable')
        local kind=dfhack.maps.getBiomeType(x,y)
        out.type=df.biome_type[kind]
        assert(type(out.type)=='string','Native biome type is unavailable')
        out.properties={};out.unavailable={}
        for _,field in ipairs({'elevation','rainfall','vegetation','temperature','evilness','drainage',
            'volcanism','savagery','salinity','region_id','landmass_id'})do
            local read,value=pcall(function()
                local v=region[field];assert(type(v)=='number','Native field is unavailable');return v
            end)
            if read then out.properties[field]=value else out.unavailable[field]=tostring(value):sub(1,180)end
        end
        out.available=true;out.complete=not next(out.unavailable)
        if out.complete then out.unavailable=nil end
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
local function armor_material_reader()
    local zones,zone_error
    return function(entry,kind)
        if not zones and not zone_error then
            local ok,value=pcall(function()
                local found,count={},0
                for _,zone in ipairs(df.global.world.world_data.resource_allotments)do
                    count=count+1;assert(count<=65536,'Production zones exceed the reading bound')
                    assert(type(zone.index)=='number' and not found[zone.index],'Invalid production zone identity')
                    found[zone.index]=zone
                end
                return found
            end)
            if ok then zones=value else zone_error=tostring(value)end
        end
        assert(zones,zone_error)
        -- SRB sale records reference a production zone and its typed allotment
        -- vector, not instantiated items. They contain no quality, fit or weight.
        local zone=zones[entry.production_zone_index]
        -- Imports retain their source production catalog. A controlling entity
        -- supplies that catalog only when the production zone ID is absent.
        if entry.production_zone_index<0 and entry.controlling_civ>=0 then
            local entity=assert(df.historical_entity.find(entry.controlling_civ),'Missing controlling entity')
            zone=entity.resource_allotment
        end
        assert(zone,'Missing production zone')
        local list=zone.resource_allotments[entry.allotment]
        local index=entry.allotment_idx
        assert(type(index)=='number' and index%1==0 and index>=0 and index<#list,'Invalid allotment index')
        local spec=assert(list[index],'Missing resource allotment')
        local class=df['resource_allotment_specifier_'..kind:lower()..'st']
        assert(class and class:is_instance(spec) and spec:getType()==entry.allotment,
            'Resource allotment class or tag does not match')
        local material=assert(dfhack.matinfo.decode(spec.mat_type,spec.mat_index),'Unknown allotment material')
        local token=material:getToken()
        assert(type(token)=='string' and token~='','Unknown material token')
        return token
    end
end
local function stock_allotments(building,material_reader)
    local out={available=false,units_by_type={},source='site_realization_building.items',
        scope='Production allotments marked for sale; live stock and paired items can differ'}
    local ok,err=pcall(function()
        local list=building.items
        out.total_records=#list;out.scanned=0
        for _,entry in ipairs(list)do
            if out.scanned>=1024 then out.truncated=true;break end
            out.scanned=out.scanned+1
            assert(type(entry.flag.for_sale)=='boolean','Native sale flag is unavailable')
            if entry.flag.for_sale then
                local token=df.resource_allotment_specifier_type[entry.allotment]
                assert(type(token)=='string','Unknown native resource allotment type')
                assert(type(entry.amount)=='number' and entry.amount%1==0 and entry.amount>=0,'Invalid native resource amount')
                out.units_by_type[token]=(out.units_by_type[token] or 0)+entry.amount
                if token:match('^ARMOR_')then
                    out.armor_materials=out.armor_materials or {}
                    local read,value=pcall(material_reader,entry,token)
                    if read then
                        local materials=out.armor_materials[token] or {}
                        out.armor_materials[token]=materials
                        materials[value]=(materials[value] or 0)+entry.amount
                    else
                        out.armor_materials_unavailable_count=(out.armor_materials_unavailable_count or 0)+1
                        out.armor_materials_unavailable=out.armor_materials_unavailable or h.array()
                        if #out.armor_materials_unavailable<8 then
                            out.armor_materials_unavailable[#out.armor_materials_unavailable+1]={
                                allotment=token,reason=tostring(value):sub(1,180)}
                        end
                    end
                end
            end
        end
        out.available=true;out.truncated=out.truncated or false
        if out.armor_materials then
            out.armor_materials_complete=not out.truncated and not out.armor_materials_unavailable
        end
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
local function live_stock(entry)
    local out={available=false,source='Shop zones assigned_items',zone_ids=h.array(),
        item_count=0,counts={},zones_scanned=0,items_scanned=0}
    local ok,err=pcall(function()
        local base=entry.zone_id and df.building.find(entry.zone_id)
        assert(base,'Shop building is not loaded')
        -- The site's civzone_id is normally Home. Its Shop subzone owns the
        -- sale goods, including items stored on tables outside map_block.items.
        local list=df.global.world.buildings.other.ZONE_SHOP
        local seen={}
        for _,zone in ipairs(list)do
            if out.zones_scanned>=8192 then out.truncated=true;break end
            out.zones_scanned=out.zones_scanned+1
            if zone.site_realization_building_id==entry.id and zone.z==base.z
                and zone.x1>=base.x1 and zone.x2<=base.x2 and zone.y1>=base.y1 and zone.y2<=base.y2 then
                assert(df.building_civzonest:is_instance(zone) and df.civzone_type[zone.type]=='Shop','Invalid native Shop zone')
                out.zone_ids[#out.zone_ids+1]=zone.id
                for _,id in ipairs(zone.assigned_items)do
                    if out.items_scanned>=4096 then out.truncated=true;break end
                    out.items_scanned=out.items_scanned+1
                    if not seen[id] then
                        seen[id]=true
                        local item=df.item.find(id)
                        assert(item,'A Shop-assigned item is unavailable')
                        local kind=df.item_type[item:getType()]
                        assert(type(kind)=='string','Unknown native shop item type')
                        out.item_count=out.item_count+1;out.counts[kind]=(out.counts[kind] or 0)+1
                    end
                end
            end
        end
        assert(#out.zone_ids>0,'No loaded Shop zone was found; the Home zone is not a stock list')
        out.available=true;out.truncated=out.truncated or false
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
function M.shops(site,position,limit,shop_type,with_stock)
    local out={available=false,source='site.realization.buildings',entries=h.array(),
        scope='Native site records; a shop location does not prove a merchant or stock is present'}
    local ok,err=pcall(function()
        if shop_type then assert(type(df.site_shop_type[shop_type])=='number','Unknown native shop type: '..shop_type)end
        local realization=site.realization
        assert(realization,'Site realization is not loaded')
        local list=realization.buildings
        local stock_sources={}
        out.total_buildings=#list;out.scanned=0
        for index,b in ipairs(list)do
            if index>=8192 then out.scan_truncated=true;break end
            out.scanned=out.scanned+1
            local kind=df.site_realization_building_type[b.type]
            assert(type(kind)=='string','Unknown native site building type')
            if kind=='shop_house' or kind=='market_square' then
                local info=b.building_info
                local class=df['site_realization_building_info_'..kind..'st']
                assert(info and class and class:is_instance(info),'Invalid native shop info tag')
                local token=df.site_shop_type[info.type]
                assert(type(token)=='string','Unknown native shop type')
                if shop_type and token~=shop_type then goto continue end
                local p={x=math.floor((site.global_min_x*48+(b.min_x+b.max_x)/2)/16),
                    y=math.floor((site.global_min_y*48+(b.min_y+b.max_y)/2)/16),z=0}
                local entry={id=b.id,type=token,building_type=kind,travel_position=p}
                if with_stock then stock_sources[b.id]=b end
                entry.facing=df.site_realization_building_facing_type and df.site_realization_building_facing_type[b.facing]
                if kind=='shop_house' then entry.name=h.text(dfhack.translation.translateName(info.name,true))end
                if b.civzone_id>=0 then
                    entry.zone_id=b.civzone_id
                    local zone=df.building.find(b.civzone_id)
                    if zone then
                        entry.position={x=zone.centerx,y=zone.centery,z=zone.z}
                        entry.bounds={x1=zone.x1,y1=zone.y1,x2=zone.x2,y2=zone.y2,z=zone.z}
                    end
                end
                if position then entry.distance=math.max(math.abs(p.x-position.x),math.abs(p.y-position.y))end
                out.entries[#out.entries+1]=entry
            end
            ::continue::
        end
        table.sort(out.entries,function(a,b)
            if a.distance~=b.distance then return a.distance<b.distance end
            return a.id<b.id
        end)
        out.matched=#out.entries
        while #out.entries>limit do table.remove(out.entries)end
        if with_stock then
            local material_reader=armor_material_reader()
            for _,entry in ipairs(out.entries)do
                entry.stock_allotments=stock_allotments(stock_sources[entry.id],material_reader)
                entry.live_stock=live_stock(entry)
            end
        end
        out.truncated=#out.entries<out.matched or out.scan_truncated==true
        out.available=true
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
function M.locate(kind,id)
    local out={available=false,kind=kind,id=id,source='gui/adv-finder',
        scope='World records, not character knowledge or visibility; locations can be historical'}
    local ok,err=pcall(function()
        assert(dfhack.isWorldLoaded(),'No world is loaded')
        assert(kind=='figure' or kind=='artifact','kind must be figure or artifact')
        assert(type(id)=='number' and id>=0 and id<=2147483647 and id==math.floor(id),'Invalid native ID')
        local object=(kind=='figure' and df.historical_figure or df.artifact_record).find(id)
        assert(object,'No such '..kind..' in this world')
        local finder=dfhack.reqscript('gui/adv-finder')
        local data=(kind=='figure' and finder.get_hf_data or finder.get_art_data)(object)
        assert(data,'Native finder returned no location record')
        out.name=h.text((kind=='figure' and finder.get_hf_name or finder.get_art_name)(object))
        for name,value in pairs(finder.LType)do if value==data.loc_type then out.location_type=name end end
        assert(out.location_type,'Unknown native finder location type')
        out.travel_position=coord(data.g_pos);out.position=coord(data.pos)
        if data.site then out.site={id=data.site.id,name=h.text(dfhack.translation.translateName(data.site.name,true))}end
        if data.sr then out.region_id=data.sr.id end
        if data.holder then out.holder_hf_id=data.holder.id end
        if kind=='figure' then out.dead=object.died_year~=-1 end
        out.available=true
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
