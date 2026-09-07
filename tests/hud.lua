-- Native HUD identities with moved icons and missing/obscured readings.
local source=...
local cells={};local reads=0;local width,height=8,4
local env=setmetatable({df={global={gps={graphical_interface={
    texpos_adventure_burden_light={11,12,13,14},texpos_adventure_burden_heavy={21,22,23,24}}}}},
    dfhack={screen={getWindowSize=function()return width,height end,
        readTile=function(x,y)reads=reads+1;return {tile=cells[x..':'..y] or 0}end}}}, {__index=_ENV})
local m=assert(load(source,'hud-fixture','t',env))()
local status={mode='adventure',map_loaded=true,can_move=true,world_epoch='one',open_panels={}}
local tests={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));tests[#tests+1]=name end

test('native burden is read without a numerical model or fixed coordinates',function()
    cells['3:2']=11
    local r=m.burden(status)
    assert(r.available and r.label=='Burdened' and r.burdened and not r.overburdened)
    assert(r.source=='native_hud_texture')
    local before=reads;m.burden(status);assert(reads-before==1)
end)
test('moved icons and changed texture identities invalidate hints',function()
    cells={['6:0']=21}
    local r=m.burden(status);assert(r.available and r.overburdened)
    env.df.global.gps.graphical_interface.texpos_adventure_burden_heavy={31,32,33,34}
    cells={['1:3']=31};assert(m.burden(status).overburdened)
    width=9;status.world_epoch='two';assert(m.burden(status).overburdened)
end)
test('absence and invalid textures never claim unburdened',function()
    cells={};local r=m.burden(status);assert(not r.available and r.reason and r.burdened==nil)
    env.df.global.gps.graphical_interface.texpos_adventure_burden_light={0}
    assert(not m.burden(status).available)
end)
test('obscured and offloaded HUD does not read the buffer',function()
    local before=reads;status.open_panels={'inventory'}
    assert(not m.burden(status).available)
    status.open_panels={};status.map_loaded=false
    assert(not m.burden(status).available and reads==before)
end)
return {passed=#tests,tests=tests,game_inputs=0}
