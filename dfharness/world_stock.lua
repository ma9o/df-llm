--@ module=true
--luacheck: globals factory
local function build(h)
-- Resource piles survive local unloading. Read only positive, referenced
-- allotments; enumerating unrelated entity production pointers is unsafe.
local M={}
local material_kinds={}
for _,name in ipairs({'THREAD','CLOTH','CRAFTS','STONE','TABLE','CABINET','CHAIR','BOX',
    'METAL','WOOD','ARMOR_BODY','ARMOR_PANTS','ARMOR_GLOVES','ARMOR_BOOTS','ARMOR_HELM',
    'CLOTHING_BODY','CLOTHING_PANTS','CLOTHING_GLOVES','CLOTHING_BOOTS','CLOTHING_HELM',
    'AMMO','WEAPON_MELEE','WEAPON_RANGED','ANVIL','GEMS','LEATHER','QUIVER','BACKPACK',
    'FLASK','BAG','BED','MEAT','BONE','HORN','SHELL','TALLOW','TOOTH','PEARL','SOAP',
    'EXTRACT','CHEESE','SKIN','POWDER'})do material_kinds[name]=true end
local function integer(value,low,high,label)
    assert(type(value)=='number' and value%1==0 and value>=low and value<=high,
        'Invalid native '..label)
    return value
end
local function failure(out,err,context)
    out.error_count=out.error_count+1
    out.complete=false
    if #out.errors<8 then
        out.errors[#out.errors+1]={context=context,reason=tostring(err):sub(1,180)}
    end
end
local function reading(source)
    return {source=source,available=false,complete=true,quantities={},scanned=0,
        error_count=0,errors=h.array()}
end
local function add(out,kind,amount)
    out.quantities[kind]=(out.quantities[kind] or 0)+amount
end
local function has_stock(quantities)
    for _,amount in pairs(quantities)do if amount>0 then return true end end
    return false
end
function M.read(ids,material,epoch)
    local out={available=false,world_epoch=epoch,sites=h.array(),
        scope='Material-bearing site resource allotments and available shop sale records; not live merchant catalogs'}
    local ok,err=pcall(function()
        assert(dfhack.isWorldLoaded(),'No world is loaded')
        assert(type(ids)=='table' and #ids<=32,'Supply at most 32 site IDs per native batch')
        local target=assert(dfhack.matinfo.find(material),'Unknown native material: '..material)
        out.material=target:getToken()
        local zones,cache={},{}
        local list=df.global.world.world_data.resource_allotments
        assert(#list<=65536,'Production zone index exceeds the reading bound')
        for _,zone in ipairs(list)do
            local id=integer(zone.index,0,2147483647,'production zone ID')
            assert(not zones[id],'Duplicate production zone ID')
            zones[id]=zone
        end
        local started=dfhack.getTickCount()
        local function matches(zone_id,entity_id,kind,index)
            integer(index,0,65535,'allotment index')
            local key=zone_id..':'..entity_id..':'..kind..':'..index
            if cache[key]~=nil then return cache[key] end
            assert(dfhack.getTickCount()-started<3000,'Material batch exceeded three seconds')
            local zone=zones[zone_id]
            -- Imported records keep the source production zone even when a
            -- different entity controls them. Its catalog indexes the counts;
            -- the entity catalog is used only without a production zone ID.
            if zone_id<0 and entity_id>=0 then
                local entity=assert(df.historical_entity.find(entity_id),'Missing controlling entity')
                assert(df.historical_entity_type[entity.type]=='SiteGovernment','Controlling entity has no site production data')
                zone=entity.resource_allotment
            end
            local specs=assert(zone,'Missing production zone').resource_allotments[kind]
            assert(index<#specs,'Positive count has no material specifier')
            local spec=assert(specs[index],'Missing material specifier')
            local token=assert(df.resource_allotment_specifier_type[kind],'Unknown allotment type')
            local class=df['resource_allotment_specifier_'..token:lower()..'st']
            assert(class and class:is_instance(spec) and spec:getType()==kind,'Allotment class or tag mismatch')
            local found=spec.mat_type==target.type and spec.mat_index==target.index
            cache[key]=found
            return found
        end
        local seen={}
        for _,id in ipairs(ids)do
            integer(id,0,2147483647,'site ID');assert(not seen[id],'Duplicate requested site ID');seen[id]=true
            local stock={resource_pile=reading('world_site.resource_pile.allotment'),
                sale_records=reading('site.realization.buildings.items[for_sale]')}
            local row={id=id,stock=stock}
            out.sites[#out.sites+1]=row
            local site=df.world_site.find(id)
            local pile=stock.resource_pile
            local read,why=pcall(function()
                assert(site,'Requested site is unavailable')
                local resources=assert(site.resource_pile,'Site resource pile is unavailable')
                assert(#resources.allotment<=65536,'Site resource entries exceed the reading bound')
                for _,entry in ipairs(resources.allotment)do
                    assert(dfhack.getTickCount()-started<3000,'Material batch exceeded three seconds')
                    pile.scanned=pile.scanned+1
                    local token=assert(df.resource_allotment_specifier_type[entry.allotment],'Unknown allotment type')
                    if material_kinds[token] then
                        local good,problem=pcall(function()
                            local counts=entry.count
                            assert(#counts<=65536,'Resource count vector exceeds the reading bound')
                            for index=0,#counts-1 do
                                if index%256==0 then
                                    assert(dfhack.getTickCount()-started<3000,'Material batch exceeded three seconds')
                                end
                                local amount=integer(counts[index],0,2147483647,'resource count')
                                -- Zero tails can outlive a specifier vector. They
                                -- require no material dereference or fallback.
                                if amount>0 and matches(entry.production_zone_index,
                                    entry.special_controlling_entity_id,entry.allotment,index)then
                                    add(pile,token,amount)
                                end
                            end
                        end)
                        if not good then failure(pile,problem,token)end
                    else
                        pile.omitted_categories=pile.omitted_categories or {}
                        pile.omitted_categories[token]=true
                    end
                end
                pile.available=true
            end)
            if not read then failure(pile,why,'site resources')end
            local sales=stock.sale_records
            sales.shops=h.array()
            read,why=pcall(function()
                assert(site,'Requested site is unavailable')
                local realization=site.realization
                if not realization then
                    sales.reason='Site realization is not loaded'
                    return
                end
                assert(#realization.buildings<=8192,'Site building list exceeds the reading bound')
                for _,building in ipairs(realization.buildings)do
                    assert(dfhack.getTickCount()-started<3000,'Material batch exceeded three seconds')
                    local kind=df.site_realization_building_type[building.type]
                    if kind=='shop_house' or kind=='market_square' then
                        local quantities={}
                        assert(#building.items<=65536,'Shop allotments exceed the reading bound')
                        for _,entry in ipairs(building.items)do
                            sales.scanned=sales.scanned+1
                            local good,problem=pcall(function()
                                assert(type(entry.flag.for_sale)=='boolean','Sale flag is unavailable')
                                if not entry.flag.for_sale then return end
                                local token=assert(df.resource_allotment_specifier_type[entry.allotment],
                                    'Unknown sale allotment type')
                                if not material_kinds[token] then return end
                                local amount=integer(entry.amount,0,2147483647,'sale count')
                                if amount>0 and matches(entry.production_zone_index,entry.controlling_civ,
                                    entry.allotment,entry.allotment_idx)then
                                    quantities[token]=(quantities[token] or 0)+amount
                                    add(sales,token,amount)
                                end
                            end)
                            if not good then failure(sales,problem,'shop '..building.id)end
                        end
                        if has_stock(quantities)then
                            local info=building.building_info
                            local class=df['site_realization_building_info_'..kind..'st']
                            assert(class and class:is_instance(info),'Shop info class mismatch')
                            local shop={id=building.id,type=df.site_shop_type[info.type],quantities=quantities,
                                travel_position={x=math.floor((site.global_min_x*48+(building.min_x+building.max_x)/2)/16),
                                    y=math.floor((site.global_min_y*48+(building.min_y+building.max_y)/2)/16),z=0}}
                            if kind=='shop_house' then shop.name=h.text(dfhack.translation.translateName(info.name,true))end
                            sales.shops[#sales.shops+1]=shop
                        end
                    end
                end
                sales.available=true
            end)
            if not read then failure(sales,why,'shop sale records')end
            stock.matched=has_stock(pile.quantities) or has_stock(sales.quantities)
            -- An unloaded catalog is an explicit source limit, not a geographic
            -- restriction on reading the site's persistent resource records.
            stock.complete=pile.available and pile.complete and sales.complete
        end
        out.available=true
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
