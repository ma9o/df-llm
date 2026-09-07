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
local m=assert(load(source,'geography-fixture','t',env))({text=function(v)return v end})
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
