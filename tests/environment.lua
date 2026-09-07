-- Visible-environment projections from isolated data, never the live world.
local source=...
local class={is_instance=function()return true end}
local env=setmetatable({dfhack={matinfo={decode=function()return {getToken=function()return 'WATER'end}end}},
    df={building_type={[0]='Door',[1]='Well',[2]='Statue'},
    building_wellst=class,building_doorst=class,building_hatchst=class}},{__index=_ENV})
local m=assert(load(source,'environment-fixture','t',env))({array=function()return {}end})
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
local function building(kind)
    return {id=0,centerx=1,centery=2,z=3,x1=1,y1=2,x2=1,y2=2,getType=function()return kind end}
end
for _,name in ipairs({'adventure_environment_optionst','adventure_environment_pickup_make_campfirest',
    'adventure_environment_ingest_materialst',
    'adventure_item_interact_heat_from_tilest','adventure_item_interact_fill_with_materialst',
    'adventure_item_interact_fill_from_containerst'})do
    env.df[name]={is_instance=function(_,o)return o.tag==name end}
end
env.df.adventure_environment_optionst.is_instance=function(_,o)
    return o.tag:find('adventure_environment_',1,true)==1
end
env.df.matter_state={[0]='Solid',[1]='Liquid',[3]='Powder'}
test('environment ingestion reads source identity without calling the mutating item factory',function()
    local r=m.option({tag='adventure_environment_ingest_materialst',mat_type=6,mat_index=0,mat_state=1,
        player_pos={x=1,y=2,z=3},target_pos={x=0,y=2,z=3},
        getIngestedItem=function()error('must not allocate a native item during observation')end})
    assert(not r.details_unavailable and r.operation=='ingest_material' and r.material_ref.token=='WATER')
    assert(r.material_ref.state=='Liquid' and r.material_ref.index==0 and r.target_position.x==0)
end)
test('snow and unavailable ingestion phases never masquerade as liquid water',function()
    local o={tag='adventure_environment_ingest_materialst',mat_type=6,mat_index=0,mat_state=3,
        player_pos={x=1,y=2,z=3},target_pos={x=0,y=2,z=3}}
    local r=m.option(o);assert(r.material_ref.state=='Powder')
    o.mat_state=99;r=m.option(o);assert(r.details_unavailable and not r.material_ref)
end)
test('environment choices use native class tags and exact coordinates including zero',function()
    local r=m.option({tag='adventure_item_interact_heat_from_tilest',item={id=0},
        pos1={x=1,y=2,z=3},pos2={x=0,y=0,z=0}})
    assert(r.operation=='heat_item' and r.item_id==0 and r.target_position.x==0 and r.player_position.z==3)
    r=m.option({tag='adventure_item_interact_fill_with_materialst',container={id=0},
        pos1={x=1,y=2,z=3},pos2={x=0,y=0,z=0},material=6,matgloss=0,state=0})
    assert(r.operation=='fill_container' and r.container_id==0 and r.material_ref.index==0 and r.material_ref.state=='Solid')
    assert(r.material_ref.token=='WATER')
end)
test('environment choices distinguish unknown tags from failed known payload reads',function()
    local r=m.option(setmetatable({tag='unknown'},{__index=function()error('unrelated payload read')end}))
    assert(not next(r))
    r=m.option({tag='adventure_item_interact_heat_from_tilest'})
    assert(r.details_unavailable and not r.target_position)
end)
test('fill from container preserves both native container IDs',function()
    local r=m.option({tag='adventure_item_interact_fill_from_containerst',container={id=1},take_from={id=0},
        pos1={x=1,y=2,z=3},pos2={x=4,y=5,z=6}})
    assert(r.operation=='fill_container' and r.container_id==1 and r.source_container_id==0)
end)
test('door flags preserve closed false and forbidden false',function()
    local b=building(0);b.door_flags={closed=false,forbidden=false,operated_by_mechanisms=true}
    local r=m.building(b)
    assert(r.id==0 and r.door.closed==false and r.door.forbidden==false and not r.unavailable)
end)
test('well presence and a zero bucket level do not claim available water',function()
    local b=building(1);b.bucket_z=0;b.well_flags={lowering=false,just_raised=true}
    local r=m.building(b)
    assert(r.well.bucket_z==0 and r.well.water_availability and r.well.flags.lowering==false)
    b.well_flags=nil;r=m.building(b);assert(r.unavailable[1]=='well' and r.well==nil)
end)
test('unrelated derived class payloads are not read',function()
    local b=setmetatable(building(2),{__index=function()error('unrelated member read')end})
    local r=m.building(b);assert(r.type=='Statue' and not r.unavailable)
end)
test('liquid regions retain material boundaries, depths and actual nearest tiles',function()
    local tiles={
        {position={x=1,y=0,z=0},kind='water',depth=1},
        {position={x=2,y=0,z=0},kind='water',depth=7},
        {position={x=2,y=1,z=0},kind='magma',depth=7},
        {position={x=4,y=0,z=0},kind='ice',depth=0},
        {position={x=5,y=0,z=0},kind='brook',depth=0}}
    local r=m.liquids(tiles,{x=0,y=0,z=0})
    assert(#r==4 and r[1].kind=='water' and r[1].tiles==2 and r[1].distance==1)
    assert(r[1].depth_min==1 and r[1].depth_max==7 and r[1].nearest.x==1)
    assert(r[2].kind=='magma' and r[3].kind=='ice' and r[4].kind=='brook')
    assert(#m.liquids({},{x=0,y=0,z=0})==0)
end)
return {passed=#names,tests=names,game_inputs=0}
