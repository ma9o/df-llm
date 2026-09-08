-- Maintained location helpers with isolated native data; no game inputs.
local source=...
local fields={'elevation','rainfall','vegetation','temperature','evilness','drainage',
    'volcanism','savagery','salinity','region_id','landmass_id'}
local region={};for _,name in ipairs(fields)do region[name]=0 end
local site={id=0,name='home',global_min_x=0,global_max_x=0,global_min_y=0,global_max_y=0}
local object={id=0,died_year=-1}
local data={loc_type=2,g_pos={x=0,y=1,z=0},pos={x=3,y=4,z=5},site=site,holder=object}
local finder={LType={None=1,Local=2,Site=3},get_hf_data=function(v)assert(v==object);return data end,
    get_art_data=function(v)assert(v==object);return data end,
    get_hf_name=function()return 'figure'end,get_art_name=function()return 'artifact'end}
local env=setmetatable({df={global={world={world_data={sites={site}}}},biome_type={[0]='FOREST'},
    historical_figure={find=function(id)return id==0 and object or nil end},
    artifact_record={find=function(id)return id==0 and object or nil end}},dfhack={
    isMapLoaded=function()return true end,isWorldLoaded=function()return true end,
    reqscript=function(name)assert(name=='gui/adv-finder');return finder end,
    translation={translateName=function(v)return v end},world={getCurrentSite=function()return site end},
    maps={isTileVisible=function()return true end,getTileBiomeRgn=function(p)assert(p.x==0);return 0,1 end,
        getRegionBiome=function(x,y)assert(x==0 and y==1);return region end,
        getBiomeType=function(x,y)assert(x==0 and y==1);return 0 end}}},{__index=_ENV})
local m=assert(load(source,'geography-fixture','t',env))({text=function(v)return v end,array=function()return {}end})
local names={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name end
test('local site reads use DFHack even when travel coordinates disagree',function()
    local s,meta=m.current_site({map_loaded=true,travel={position={x=99,y=99}}})
    assert(s==site and meta.available and meta.present and meta.source=='dfhack.world.getCurrentSite')
    env.dfhack.world.getCurrentSite=function()return nil end
    s,meta=m.current_site({map_loaded=true,travel={position={x=0,y=0}}})
    assert(not s and meta.available and meta.present==false)
end)
test('offloaded travel has a bounded explicit coordinate fallback; failure is not no site',function()
    env.dfhack.world.getCurrentSite=function()error('Must not call local helper during travel')end
    local s,meta=m.current_site({map_loaded=false,travel={position={x=0,y=0}}})
    assert(s==site and meta.source=='native_travel_site_bounds')
    s,meta=m.current_site({map_loaded=false})
    assert(not s and not meta.available and meta.present==nil and meta.reason)
    s,meta=m.current_site({map_loaded=true})
    assert(not s and not meta.available and meta.present==nil)
end)
test('biome coordinates and zero values survive; missing fields remain partial',function()
    local p={x=0,y=0,z=0}
    local r=m.biome(p)
    assert(r.available and r.complete and r.region.x==0 and r.properties.salinity==0 and r.type=='FOREST')
    region.rainfall=nil;r=m.biome(p)
    assert(r.available and not r.complete and r.unavailable.rainfall and r.properties.salinity==0)
    assert(r.properties.rainfall==nil)
    env.dfhack.maps.isTileVisible=function()return false end
    r=m.biome(p);assert(not r.available and not r.properties and r.reason)
end)
test('native shop records rank destinations without traversing unrelated building info',function()
    env.df.site_realization_building_type={[0]='house',[3]='shop_house',[5]='market_square'}
    env.df.site_shop_type={[0]='GeneralImports',[8]='Armorsmith',GeneralImports=0,Armorsmith=8}
    local tag={is_instance=function(_,v)return v.tag=='shop' end}
    env.df.site_realization_building_info_shop_housest=tag
    env.df.site_realization_building_info_market_squarest=tag
    env.df.building={find=function(id)if id==0 then return {centerx=0,centery=5,z=6}end end}
    site.realization={buildings={
        {id=4,type=3,min_x=64,max_x=64,min_y=16,max_y=16,civzone_id=-1,building_info={tag='shop',type=8,name='Armor'}},
        {id=0,type=5,min_x=0,max_x=0,min_y=16,max_y=16,civzone_id=0,building_info={tag='shop',type=0}},
        setmetatable({id=7,type=0},{__index=function()error('Unrelated union read')end})}}
    local r=m.shops(site,{x=0,y=1},1)
    assert(r.available and r.scanned==3 and r.matched==2 and r.truncated and #r.entries==1)
    local e=r.entries[1]
    assert(e.id==0 and e.type=='GeneralImports' and e.travel_position.x==0 and e.position.x==0 and e.distance==0)
    assert(not e.name)
    r=m.shops(site,nil,10)
    assert(r.available and not r.truncated and r.entries[2].name=='Armor' and not r.entries[2].position)
    r=m.shops(site,{x=0,y=1},1,'Armorsmith')
    assert(r.available and r.matched==1 and not r.truncated and r.entries[1].id==4)
    r=m.shops(site,nil,10,'Typo');assert(not r.available and r.reason)
end)
test('missing site data and wrong shop unions are unknown rather than empty catalogs',function()
    local r=m.shops({},nil,10);assert(not r.available and r.reason)
    site.realization.buildings[1].building_info.tag='other'
    r=m.shops(site,nil,10);assert(not r.available and r.reason)
    r=m.shops({realization={buildings={}}},nil,10)
    assert(r.available and r.matched==0 and r.truncated==false)
end)
local function stock_site(items)
    return {global_min_x=0,global_min_y=0,realization={buildings={{id=105,type=3,min_x=0,max_x=0,
        min_y=0,max_y=0,civzone_id=0,building_info={tag='shop',type=0,name='store'},items=items}}}}
end
test('sale allotments preserve zero and skip non-sale payloads',function()
    env.df.resource_allotment_specifier_type={[0]='ARMOR_BODY',[1]='WEAPON_MELEE'}
    local s=stock_site({{flag={for_sale=true},allotment=0,amount=0},
        {flag={for_sale=true},allotment=1,amount=15},
        setmetatable({flag={for_sale=false}},{__index=function()error('Not for sale')end})})
    local r=m.shops(s,nil,1,nil,true).entries[1].stock_allotments
    assert(r.available and r.units_by_type.ARMOR_BODY==0 and r.units_by_type.WEAPON_MELEE==15)
    assert(r.scanned==3 and not r.truncated)
    s.realization.buildings[1].items[1].flag.for_sale=nil
    r=m.shops(s,nil,1,nil,true).entries[1].stock_allotments
    assert(not r.available and r.reason)
end)
test('stock is read only for requested and returned shop entries',function()
    local reads=0
    local s=stock_site({})
    local far=setmetatable({id=106,type=3,min_x=16,max_x=16,min_y=0,max_y=0,civzone_id=-1,
        building_info={tag='shop',type=0,name='far'}},{__index=function(_,key)
            if key=='items' then reads=reads+1;error('Unrequested stock')end
        end})
    s.realization.buildings[2]=far
    assert(m.shops(s,{x=0,y=0},1,nil,true).entries[1].id==105 and reads==0)
    local r=m.shops(s,nil,2)
    assert(not r.entries[1].stock_allotments and not r.entries[2].stock_allotments and reads==0)
end)
test('allotment truncation uses counts independently of native vector indexing',function()
    local items={};for i=1,1025 do items[i]={flag={for_sale=true},allotment=0,amount=1}end
    local r=m.shops(stock_site(items),nil,1,nil,true).entries[1].stock_allotments
    assert(r.available and r.scanned==1024 and r.truncated and r.units_by_type.ARMOR_BODY==1024)
    assert(not r.armor_materials_complete and r.armor_materials_unavailable_count==1024)
    assert(#r.armor_materials_unavailable==8)
end)
test('armor material lookup follows native production references, preserving zero and source records',function()
    local spec={mat_type=0,mat_index=2,getType=function()return 0 end}
    local list=setmetatable({[0]=spec},{__len=function()return 1 end})
    env.df.global.world.world_data.resource_allotments={{index=17,resource_allotments={[0]=list}}}
    env.df.resource_allotment_specifier_armor_bodyst={is_instance=function(_,v)return v==spec end}
    env.dfhack.matinfo={decode=function(t,i)
        assert(t==0 and i==2);return {getToken=function()return 'INORGANIC:IRON' end}
    end}
    local zero={flag={for_sale=true},allotment=0,amount=0,production_zone_index=17,
        allotment_idx=0,controlling_civ=-1}
    local stocked={flag={for_sale=true},allotment=0,amount=3,production_zone_index=17,
        allotment_idx=0,controlling_civ=-1}
    local s=stock_site({zero})
    local r=m.shops(s,nil,1,nil,true).entries[1].stock_allotments
    assert(r.available and r.armor_materials_complete and r.armor_materials.ARMOR_BODY['INORGANIC:IRON']==0)
    s.realization.buildings[1].items[2]=stocked
    r=m.shops(s,nil,1,nil,true).entries[1].stock_allotments
    assert(r.armor_materials.ARMOR_BODY['INORGANIC:IRON']==3 and r.units_by_type.ARMOR_BODY==3)
    assert(not r.quality and not r.weight_kg and not r.item_ids and stocked.amount==3)
end)
test('controlling entity references and unknown material readers never masquerade as missing stock',function()
    local spec={getType=function()return 0 end,mat_type=0,mat_index=2}
    env.df.resource_allotment_specifier_armor_bodyst={is_instance=function(_,v)return v==spec end}
    local list=setmetatable({[0]=spec},{__len=function()return 1 end})
    local entity={resource_allotment={resource_allotments={[0]=list}}}
    env.df.historical_entity={find=function(id)assert(id==0);return entity end}
    local entry={flag={for_sale=true},allotment=0,amount=2,production_zone_index=-1,
        allotment_idx=0,controlling_civ=0}
    local function read()return m.shops(stock_site({entry}),nil,1,nil,true).entries[1].stock_allotments end
    assert(read().armor_materials.ARMOR_BODY['INORGANIC:IRON']==2)
    for _,break_read in ipairs({
        function()entry.allotment_idx=1 end,
        function()entry.allotment_idx=0;spec.getType=function()return 1 end end,
        function()spec.getType=function()return 0 end;env.dfhack.matinfo.decode=function()return nil end end,
    })do
        break_read()
        local r=read()
        assert(r.available and r.units_by_type.ARMOR_BODY==2 and r.armor_materials_complete==false)
        assert(not next(r.armor_materials) and r.armor_materials_unavailable_count==1)
    end
end)
test('imported shop goods retain their source production material catalog',function()
    local spec={getType=function()return 0 end,mat_type=0,mat_index=2}
    env.df.resource_allotment_specifier_armor_bodyst={is_instance=function(_,v)return v==spec end}
    local list=setmetatable({[0]=spec},{__len=function()return 1 end})
    env.df.global.world.world_data.resource_allotments={{index=17,resource_allotments={[0]=list}}}
    env.df.historical_entity.find=function()error('Controlling entity does not define imported material')end
    env.dfhack.matinfo.decode=function()return {getToken=function()return 'INORGANIC:STEEL'end}end
    local e={flag={for_sale=true},allotment=0,amount=2,production_zone_index=17,allotment_idx=0,controlling_civ=0}
    local r=m.shops(stock_site({e}),nil,1,nil,true).entries[1].stock_allotments
    assert(r.armor_materials_complete and r.armor_materials.ARMOR_BODY['INORGANIC:STEEL']==2)
end)
test('shop summaries and non-armor stock do not read production materials',function()
    env.df.global.world.world_data.resource_allotments=setmetatable({},
        {__index=function()error('Unrequested production material scan')end})
    local s=stock_site({{flag={for_sale=true},allotment=1,amount=5}})
    assert(m.shops(s,nil,1).available)
    local r=m.shops(s,nil,1,nil,true).entries[1].stock_allotments
    assert(r.available and r.units_by_type.WEAPON_MELEE==5 and not r.armor_materials)
end)
test('live stock comes from the Shop subzone, never the Home zone or another building',function()
    local old_find=env.df.building.find
    local home={id=0,x1=0,y1=0,x2=10,y2=10,z=0,centerx=5,centery=5,assigned_items={99}}
    env.df.building.find=function(id)if id==0 then return home end end
    env.df.building_civzonest={is_instance=function(_,v)return v.tag=='zone'end}
    env.df.civzone_type={[0]='Home',[1]='Shop'}
    env.df.item_type={[0]='ARMOR'}
    env.df.item={find=function(id)assert(id~=99,'Home contents must not be used');return {getType=function()return 0 end}end}
    local shop={tag='zone',id=1,type=1,site_realization_building_id=105,x1=1,y1=1,x2=9,y2=9,z=0,assigned_items={0,1}}
    local far={tag='zone',id=2,type=1,site_realization_building_id=105,x1=20,y1=20,x2=29,y2=29,z=0,assigned_items={99}}
    env.df.global.world.buildings={other={ZONE_SHOP={far,shop}}}
    local s=stock_site({})
    local r=m.shops(s,nil,1,nil,true).entries[1].live_stock
    assert(r.available and r.item_count==2 and r.counts.ARMOR==2 and #r.zone_ids==1 and r.zone_ids[1]==1)
    shop.assigned_items={};r=m.shops(s,nil,1,nil,true).entries[1].live_stock
    assert(r.available and r.item_count==0)
    env.df.global.world.buildings.other.ZONE_SHOP={far}
    r=m.shops(s,nil,1,nil,true).entries[1].live_stock
    assert(not r.available and r.reason)
    env.df.building.find=old_find
end)
test('finder serializes coordinates and IDs without retaining native references',function()
    local r=m.locate('figure',0)
    assert(r.available and r.location_type=='Local' and r.dead==false and r.holder_hf_id==0)
    assert(r.site.id==0 and r.travel_position.x==0 and r.position.z==5 and not r.holder)
    r.position.z=100;r.site.name='changed'
    assert(data.pos.z==5 and site.name=='home')
    r=m.locate('artifact',0);assert(r.available and r.name=='artifact' and r.dead==nil)
end)
test('unknown location is explicit and finder failures never invent coordinates',function()
    data={loc_type=1}
    local r=m.locate('figure',0)
    assert(r.available and r.location_type=='None' and not r.travel_position and not r.position)
    for _,args in ipairs({{'figure',1},{'figure',-1},{'unit',0}})do
        r=m.locate(table.unpack(args));assert(not r.available and r.reason and not r.position)
    end
    finder.get_hf_data=function()error('Missing helper')end
    r=m.locate('figure',0);assert(not r.available and r.reason)
end)
return {passed=#names,tests=names,game_inputs=0}
