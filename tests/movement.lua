-- Movement choices use native creature definitions and probed page bounds.
local source,binding_source=...
local raw={ [0]={action_string_idx=0},[1]={action_string_idx=1} }
local vector=setmetatable(raw,{__len=function()return 2 end})
local native_ipairs=function(v)
    if v==vector then local i=-1;return function()i=i+1;if i<2 then return i,v[i] end end end
    return ipairs(v)
end
local unit={id=1,flags1={hidden_in_ambush=false},status={command_gait_index={[0]=0}},
    body={body_plan={gait_info={[0]=vector}}}}
local panel={open=true,speed_sneak_un=unit,gait_type=0,scroll_gait=5}
local keys={};for i=1,20 do keys['OPTION'..i]=i end
local env=setmetatable({ipairs=native_ipairs,df={interface_key=keys,gait_type={_last_item=0,[0]='WALK'},
    global={game={main_interface={adventure={movement_options=panel}}},
        world={raws={creatures={action_strings={[0]='Walk',[1]='Creep'}}}}}},
    dfhack={getDFVersion=function()return 'v0.53.16 win64 STEAM' end}},{__index=_ENV})
local bindings=assert(load(binding_source,'movement-binding','t',env))({text=function(s)return s end,
    normalize_ui=function()end})
local m=assert(load(source,'movement-fixture','t',env))({array=function()return {} end,text=function(s)return s end,bindings=bindings})
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('native gait zero and false sneaking survive',function()
    local r=m.character(unit);assert(r.available and r.sneaking==false and r.selected_gaits.WALK==0)
end)
test('route window includes a detoured character and its original target',function()
    local r=m.route_window({x=144,y=144},{x=61,y=69,z=136},{x=48,y=80,z=136},41,21)
    assert(r.target_included and r.height>=22 and r.width==41)
    for _,p in ipairs({{x=61,y=69},{x=48,y=80}})do
        assert(p.x>=r.origin.x and p.x<r.origin.x+r.width and p.y>=r.origin.y and p.y<r.origin.y+r.height)
    end
end)
test('bounded route windows keep the player and report an excluded distant goal',function()
    local r=m.route_window({x=144,y=144},{x=0,y=0,z=0},{x=143,y=143,z=0},41,21)
    assert(r.origin.x==0 and r.origin.y==0 and r.width==101 and r.height==61 and not r.target_included)
    r=m.route_window({x=12,y=12},{x=11,y=11,z=0},{x=0,y=0,z=0},41,21)
    assert(r.origin.x==0 and r.origin.y==0 and r.width==12 and r.height==12 and r.target_included)
end)
test('a distant destination retains a local margin for route detours',function()
    local r=m.route_window({x=144,y=144},{x=70,y=70,z=0},{x=1000,y=1000,z=0},41,21)
    assert(not r.target_included and r.origin.x<=65 and r.origin.y<=65)
    assert(r.origin.x+r.width>75 and r.origin.y+r.height>75)
end)
test('visible units outside the crop or z-level remain in the controller observation',function()
    local units={{id=1,position={x=0,y=0,z=0}},
        {id=2,position={x=22,y=9,z=0}},{id=3,position={x=0,y=0,z=1}}}
    local r=m.map_units(units,{x=0,y=0,z=0},21,21,1)
    assert(#r==3 and r[1].in_map and not r[2].in_map and not r[3].in_map)
    assert(r[1].glyph=='@' and units[1].in_map==nil)
end)
test('gaits use native indices without ASCII labels and correct a stale single-page offset',function()
    local r=m.menu({rows={}})
    local o=r.options[2]
    assert(o.gait_index==1 and o.selection.method=='native_hotkey' and not o.click and panel.scroll_gait==5)
    local adjustment=bindings.scroll(r,o)
    assert(adjustment.maximum==0 and panel.scroll_gait==0 and unit.status.command_gait_index[0]==0)
    assert(bindings.selection_key(m.menu({rows={}}),o)=='OPTION2')
end)
test('unknown movement state remains unavailable and missing target cannot select',function()
    local selected=unit.status;unit.status=nil
    assert(not m.character(unit).available)
    unit.status=selected;panel.speed_sneak_un=nil
    assert(m.menu({rows={}}).selection_unavailable)
    panel.speed_sneak_un=unit
end)
test('processing visibility reads IDs with the same filter as full observations',function()
    env.df.global.world.units={active={{id=0},{id=2,hidden=true},{id=3,visible=false},{id=4}}}
    env.dfhack.units={isVisible=function(u)return u.visible~=false end,
        isHidden=function(u)return u.hidden==true end}
    env.dfhack.maps={getTileSize=function()return 96,144,160 end}
    env.dfhack.units.getUnitsInBox=function(x1,y1,z1,x2,y2,z2,filter)
        assert(x1==0 and y1==0 and z1==0 and x2==95 and y2==143 and z2==159)
        local result={}
        for _,u in ipairs(env.df.global.world.units.active)do
            if filter(u)then result[#result+1]=u end
        end
        return result
    end
    local partial=m.visible_units(true)
    local projections=0
    local full=m.visible_units(true,function(u)projections=projections+1;return {id=u.id,name='name'}end)
    assert(partial.units_available and not partial.units_truncated and #partial.units==2 and projections==2)
    for i,u in ipairs(partial.units)do assert(u.id==full.units[i].id and not u.name)end
end)
test('visibility bounds count visible entries and total scanned native units',function()
    local active={};env.df.global.world.units.active=active
    for i=1,501 do active[i]={id=i}end
    local r=m.visible_units(true);assert(#r.units==500 and r.units_truncated and r.units_available)
    for i=1,32769 do active[i]={id=i,visible=false}end
    r=m.visible_units(true);assert(#r.units==0 and r.units_truncated and r.units_available)
    active[32769]=nil
    r=m.visible_units(true);assert(#r.units==0 and not r.units_truncated and r.units_available)
end)
test('offloaded visibility avoids native pointers and read failure cannot claim an empty set',function()
    env.df.global.world.units=nil
    local r=m.visible_units(false);assert(r.units_available and #r.units==0 and not r.units_truncated)
    r=m.visible_units(true);assert(not r.units_available and r.units_unavailable)
end)
return {passed=#names,tests=names,game_inputs=0}
