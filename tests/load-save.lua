-- Native title catalog/normalization fixtures; no live game inputs.
local source=...
local names={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name end
local function vector(values)
    local v={};for i,x in ipairs(values)do v[i-1]=x end
    return setmetatable(v,{__len=function()return #values end,__ipairs=function(t)
        local i=-1;return function()i=i+1;if i<#t then return i,t[i]end end end})
end
local target={filename_noext='night',full_path='/save/night',world_header={id1=2,id2=3}}
local s,screen,callbacks,inputs,stalled
local gps={mouse_x=1,mouse_y=2,precise_mouse_x=3,precise_mouse_y=4,tile_pixel_x=10,tile_pixel_y=15}
local env=setmetatable({dfhack_flags={module=true},df={global={gps=gps,enabler={tracking_on=true}},
    viewscreen_titlest={is_instance=function(_,v)return v==s end},viewscreen_loadgamest={is_instance=function(_,v)return v=='loader' end},
    title_mode_type={MAIN_MENU=0,CONTINUE_ACTIVE_WORLD=2,CONTINUE_ACTIVE=3},main_choice_type={Continue=1}},
    dfhack={gui={getCurViewscreen=function()return screen end},isWorldLoaded=function()return false end,
        isMapLoaded=function()return false end,screen={getWindowSize=function()return 180,77 end},
        filesystem={isfile=function(path)return path=='/save/night/world.sav' end},
        timeout=function(_,_,fn)callbacks[#callbacks+1]=fn end}}, {__index=_ENV})
env.require=function(name)
    assert(name=='gui')
    return {simulateInput=function(_,key)
        if type(key)=='table' then
            if s.mode==2 then s.scroll_position_world_choice=0 else s.scroll_position_game_choice=0 end
            return
        end
        assert(key=='_MOUSE_L')
        inputs=inputs+1
        if stalled then return end
        local row=(gps.mouse_y-41)//3
        if s.mode==0 then assert(row==0);s.mode=2
        elseif s.mode==2 then assert(row==1);s.mode=3
        else assert(row==1);screen='loader'end
    end}
end
local function reset()
    s={mode=0,game_start_proceed=0,menu_line_id=vector({1}),savegame_header=vector({target}),
        savegame_header_world=vector({{world_header={id1=7,id2=8}},target}),
        savegame_header_game=vector({{filename_noext='different'},target})}
    screen=s;callbacks={};inputs=0;stalled=false
    assert(load(source,'load-save-fixture','t',env))()
end
local function drain()
    for _=1,10 do if #callbacks==0 then return end;table.remove(callbacks,1)()end
    error('Unbounded native load loop')
end
test('exact native world and save identities survive native scroll normalization',function()
    reset();env.start('night');drain()
    assert(env.status().phase=='loading' and inputs==3 and screen=='loader')
    assert(gps.mouse_x==1 and gps.mouse_y==2 and gps.precise_mouse_x==3 and gps.precise_mouse_y==4)
end)
test('an ineffective title selection is not repeated',function()
    reset();stalled=true;env.start('night');drain()
    assert(env.status().phase=='failed' and inputs==1 and env.status().reason:find('not repeated',1,true))
end)
test('paths, absent saves and active title operations fail before any input',function()
    reset()
    for _,name in ipairs({'../save','current','missing'})do assert(not pcall(env.start,name));assert(inputs==0)end
    s.game_start_proceed=1;assert(not pcall(env.start,'night'));assert(inputs==0)
end)
return {passed=#names,tests=names,game_inputs=0}
