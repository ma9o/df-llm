local source=...
local a={sleep_hours=8,sleeping=0,sleep_interrupt=0,sleep_sleep=true,sleep_until_dawn=false,
    sleeping_indoors=false,sleeping_underground=false}
local panel={open=false,no_sky=false}
local verified=true
local h={array=function()return {}end,bindings={
    support=function()return {native_hotkey_available=verified}end,
    fixed=function(o,key,available)if available then o.selection={method='native_key',key=key}end;return o end,
    catalog=function(m)return m end}}
local env=setmetatable({df={game_type={[1]='ADVENTURE_MAIN',[4]='ADVENTURE_ARENA'},
    global={adventure=a,game={main_interface={adventure={sleep=panel}}},gametype=1,
        cur_year_tick=18397,cur_season_tick=1839,world={world_data={world_width=129}}}}},{__index=_ENV})
local m=assert(load(source,'rest-fixture','t',env))(h)
local names={}
local function test(name,fn)local ok,e=pcall(fn);assert(ok,name..': '..tostring(e));names[#names+1]=name end
test('closed rest panels do not read inactive fields',function()
    panel.no_sky=nil;setmetatable(panel,{__index=function()error('inactive field')end})
    assert(not m.open() and m.menu()==nil)
    setmetatable(panel,nil);panel.no_sky=false
end)
test('native rest state preserves zero false and fixed controls without ASCII',function()
    panel.open=true
    local r=m.menu()
    assert(r.settings.sleeping==0 and r.settings.sleep_until_dawn==false and r.no_sky==false)
    assert(#r.options==9 and not r.selection_unavailable)
    assert(r.options[4].selection.key=='ADVENTURE_LIST_SCROLL_UP')
    assert(r.options[8].selection.key=='SELECT' and r.settings.model.hours_max==24)
    panel.no_sky=true;assert(#m.menu().options==8);panel.no_sky=false
end)
test('unsupported builds expose settings but no verified controls or time model',function()
    verified=false;local r=m.menu()
    assert(r.settings.available and not r.settings.model and r.selection_unavailable)
    for _,o in ipairs(r.options)do assert(not o.selection)end
    verified=true
end)
test('missing rest settings remain unavailable instead of ready or idle',function()
    a.sleeping=nil;local r=m.state();assert(not r.available and r.sleeping==nil)
    assert(m.menu().selection_unavailable);a.sleeping=0
end)
local function state(tick,x,travel)
    env.df.global.cur_year_tick=tick;env.df.global.cur_season_tick=math.floor((tick%100800)/10)
    local s={mode='adventure',year_tick=tick,position={x=42,y=62,z=129},
        map_origin={x=x*768-42,y=0,z=0},travel={active=travel==true}}
    if travel then s.travel.position={x=x*48+3,y=0,z=0} end
    return s
end
test('native dawn clock matches local longitude and preserves a complete read-only state',function()
    local s=state(18397,6)
    local r=m.state(s)
    assert(r.available and r.dawn.available and r.dawn.phase==678)
    assert(math.type(r.dawn.remaining_calendar_ticks)=='integer')
    assert(r.dawn.remaining_calendar_ticks==1114 and r.dawn.world_region_x==6)
    assert(a.sleeping==0 and a.sleep_until_dawn==false and s.position.x==42)
end)
test('exact dawn targets the next day while the prior calendar tick needs only one',function()
    local before=m.dawn(state(310,6));local at=m.dawn(state(311,6));local after=m.dawn(state(312,6))
    assert(before.phase==504 and before.remaining_calendar_ticks==1)
    assert(at.phase==506 and at.remaining_calendar_ticks==1200)
    assert(after.phase==508 and after.remaining_calendar_ticks==1199)
end)
test('dawn uses native year and season rollover and both map and travel coordinates',function()
    local r=m.dawn(state(403199,6,true))
    assert(r.available and r.phase==2282 and r.remaining_calendar_ticks==312)
    local local_r=m.dawn(state(403199,6))
    assert(local_r.phase==r.phase)
    local zero=m.dawn(state(317,0))
    assert(zero.available and zero.phase==506 and zero.world_region_x==0)
end)
test('dawn never adopts inactive local coordinates when travel position is missing',function()
    local s=state(311,6,true);s.travel.position=nil
    assert(not m.dawn(s).available)
end)
test('dawn unsupported builds and arena clocks remain explicit without disabling hour settings',function()
    local s=state(311,6)
    env.df.global.gametype=4;assert(not m.dawn(s).available and m.state().available)
    env.df.global.gametype=1;verified=false
    assert(not m.dawn(s).available and m.state().available)
    verified=true
end)
test('missing or inconsistent dawn clock readings never produce a guessed duration',function()
    local s=state(311,6)
    env.df.global.cur_season_tick=nil;assert(not m.dawn(s).available)
    s=state(311,6);s.year_tick=312;assert(not m.dawn(s).available)
    s=state(311,129);assert(not m.dawn(s).available)
    s=state(311,6);env.df.global.world.world_data.world_width=0;assert(not m.dawn(s).available)
    env.df.global.world.world_data.world_width=129
end)
return {passed=#names,tests=names,game_inputs=0}
