-- Native-shaped fixtures run in an isolated environment: no game writes/inputs.
local source=...
local function vector(values,count)
    local out={}
    for i,v in ipairs(values)do out[i-1]=v end
    return setmetatable(out,{__len=function()return count or #values end})
end
local function site(id,kind)
    return {id=id,type=kind or 0,name={'English','Native'},global_min_x=0,global_max_x=0,
        global_min_y=0,global_max_y=0}
end
local world={world_data={sites=vector({site(0)})},map={region_x=0,region_y=0},cur_savegame={save_dir='fixture'}}
local env=setmetatable({df={global={world=world,cur_year=0,cur_year_tick=0},
    world_site_type={_first_item=0,_last_item=4,[0]='Cave',[1]='LairShrine',[2]='Fortress',[3]='Monument',[4]='FutureSite'},
    lair_type={_first_item=-1,_last_item=0,[-1]='NONE',[0]='SIMPLE_BURROW'},
    fortress_type={_first_item=0,_last_item=0,[0]='CASTLE'},monument_type={_first_item=0,_last_item=0,[0]='TOMB'}},
    dfhack={isWorldLoaded=function()return true end,isMapLoaded=function()return true end,
        translation={translateName=function(name,english)return name[english and 1 or 2]end},
        world={getAdventurer=function()return {id=0}end},units={getPosition=function()return 0,0,0 end}}},
    {__index=_ENV})
local m=assert(load(source,'world-scan-fixture','t',env))({array=function()return {}end,text=function(v)return v end})
local names={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name end
test('snapshot preserves zero and copies coordinate bounds without native references',function()
    local r=m.snapshot('epoch')
    assert(r.available and r.complete and r.total==1 and r.scanned==1 and not r.truncated)
    assert(r.world.year==0 and r.world.year_tick==0 and r.world.epoch=='epoch')
    assert(r.origin.x==0 and r.origin.y==0 and r.sites[1].id==0)
    local s=r.sites[1]
    assert(s.name=='English' and s.native_name=='Native' and s.type=='Cave')
    assert(s.bounds.x1==0 and s.bounds.x2==2 and s.position.x==1 and s.position.z==0)
    s.name='changed';s.bounds.x1=20
    assert(world.world_data.sites[0].name[1]=='English' and world.world_data.sites[0].global_min_x==0)
end)
test('subtype reads follow tags and absent optional records differ from failures',function()
    local records={site(0),site(1,1),site(2,2),site(3,3),site(4,1),site(5,1)}
    local fields={'lair_type','fortress_type','monument_type'}
    records[1]=setmetatable(records[1],{__index=function(_,k)assert(k~='subtype_info','Inactive subtype read')end})
    for i=2,4 do
        records[i].subtype_info=setmetatable({}, {__index=function(_,key)
            assert(key==fields[i-1],'Inactive tagged field');return 0 end})
    end
    records[6].subtype_info={lair_type=999}
    world.world_data.sites=vector(records)
    local r=m.snapshot('epoch')
    assert(r.error_count==0 and #r.sites==6)
    assert(r.sites[2].subtype=='SIMPLE_BURROW' and r.sites[3].subtype=='CASTLE' and r.sites[4].subtype=='TOMB')
    assert(r.sites[5].subtype_present==false and r.sites[5].subtype_unavailable==nil)
    assert(r.sites[6].subtype_present==true and r.sites[6].subtype_unavailable)
end)
test('one unreadable site does not hide healthy results or claim full coverage',function()
    local bad=site(2);bad.global_max_y=-1
    world.world_data.sites=vector({site(0),bad,site(3,4)})
    local r=m.snapshot('epoch')
    assert(r.available and not r.complete and r.error_count==1 and #r.errors==1 and #r.sites==2)
    assert(r.errors[1].index==1 and r.sites[2].type=='FutureSite')
end)
test('catalog reads running enums without loading a world or enumerating sites',function()
    env.dfhack.isWorldLoaded=function()return false end
    world.world_data.sites=setmetatable({}, {__len=function()error('Catalog must not scan sites')end})
    local r=m.snapshot(nil,true)
    assert(r.available and r.complete and #r.tokens.site==5 and #r.tokens.lair_type==1)
    assert(r.tokens.lair_type[1]=='SIMPLE_BURROW' and not r.world)
    env.df.monument_type=nil;r=m.snapshot(nil,true)
    assert(r.available and not r.complete and r.unavailable.monument_type and r.tokens.site)
    r=m.snapshot('epoch')
    assert(not r.available and r.reason:find('No world is loaded',1,true))
    env.dfhack.isWorldLoaded=function()return true end
end)
test('empty world and unavailable origin are explicit without local map or UI reads',function()
    world.world_data.sites=vector({})
    env.dfhack.isMapLoaded=function()return false end
    env.dfhack.world.getAdventurer=function()error('No local character access while offloaded')end
    local r=m.snapshot('epoch')
    assert(r.available and r.complete and r.total==0 and not r.origin)
    env.dfhack.isMapLoaded=function()return true end
    r=m.snapshot('epoch')
    assert(r.available and r.complete and r.origin_unavailable and not r.origin)
end)
test('site index traversal and error diagnostics have explicit independent bounds',function()
    world.world_data.sites=setmetatable({}, {__len=function()return 40000 end,
        __index=function(_,i)assert(i<32768,'Read beyond scan bound');error('Unreadable site')end})
    local r=m.snapshot('epoch')
    assert(r.available and not r.complete and r.truncated and r.scanned==32768 and r.total==40000)
    assert(r.error_count==32768 and #r.errors==20 and #r.sites==0)
end)
return {passed=#names,tests=names,game_inputs=0}
