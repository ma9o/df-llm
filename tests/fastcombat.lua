local source=...
local names={}
local function test(name,fn)local ok,e=pcall(fn);assert(ok,name..': '..tostring(e));names[#names+1]=name end
local function fixture()
    local f={inputs=0,queue={},enabled=true,phase=1,screen=true,loaded=true,adventure=true,simulation_timer=20}
    local w={onInput=function(_,keys)
        assert(keys.SELECT and f.phase~=0 and f.phase~=2)
        f.inputs=f.inputs+1
    end}
    local env=setmetatable({require=function(name)
        assert(name=='plugins.overlay');return {isOverlayEnabled=function()return f.enabled end,
            get_state=function()return {db={['advtools.fastcombat']={widget=w}}}end}
    end,df={global={adventure=setmetatable({}, {__index=function(_,k)
        assert(k=='player_control_state');return f.phase end})},
        viewscreen_dungeonmodest={is_instance=function()return f.screen end},
        adventure_game_loop_type={TAKING_INPUT=0,TAKING_TOO_LONG_INPUT=2}},
        dfhack={isMapLoaded=function()return f.loaded end,world={isAdventureMode=function()return f.adventure end},
            gui={getCurViewscreen=function()return {}end},
            timeout=function(_,mode,fn)assert(mode=='frames');f.queue[#f.queue+1]=fn end}}, {__index=_ENV})
    f.api=assert(load(source,'fastcombat-fixture','t',env))()
    f.session={world_epoch='a',active_dispatch='d',dispatches={d={}}}
    f.request={parent_dispatch='d',fastcombat=true};f.receipt={}
    function f:arm()self.api.arm(self.session,self.request,self.receipt)end
    function f:tick()table.remove(self.queue,1)()end
    return f
end
test('support discovery and undelegated inputs do not activate the overlay',function()
    local f=fixture();assert(f.api.support().available);assert(f.inputs==0 and #f.queue==0)
    f.request.fastcombat=nil;f:arm();assert(f.inputs==0 and not f.receipt.presentation)
end)
test('completed input delegates presentation to the installed overlay only',function()
    local f=fixture();f:arm();assert(f.inputs==1 and f.receipt.presentation.activated)
    assert(f.simulation_timer==20 and #f.queue==0)
end)
test('disabled overlays are respected and unavailable acceleration is diagnostic',function()
    local f=fixture();f.enabled=false;f:arm()
    assert(f.inputs==0 and not f.receipt.presentation.available and f.receipt.presentation.reason)
end)
test('ready input and long-action prompts are never acknowledged by acceleration',function()
    for _,phase in ipairs({0,2})do
        local f=fixture();f.phase=phase;f:arm();f:tick()
        assert(f.inputs==0 and not f.receipt.presentation.activated)
    end
end)
test('one deferred activation covers native processing starting next frame',function()
    local f=fixture();f.phase=0;f:arm();f.phase=1;f:tick()
    assert(f.inputs==1 and f.receipt.presentation.activated and #f.queue==0)
end)
test('expired or interrupted input cannot activate a later action',function()
    for _,kind in ipairs({'world','dispatch','interrupt','settled','error'})do
        local f=fixture();f.phase=0;f:arm();f.phase=1
        if kind=='world' then f.session.world_epoch='b'
        elseif kind=='dispatch' then f.session.active_dispatch='next'
        elseif kind=='interrupt' then f.session.dispatches.d.interrupted=true
        elseif kind=='settled' then f.receipt.settled=true
        else f.receipt.error='failed' end
        f:tick();assert(f.inputs==0)
    end
end)
test('non-adventure screens and offloaded maps never receive overlay inputs',function()
    for _,field in ipairs({'screen','loaded','adventure'})do
        local f=fixture();f[field]=false;f:arm();f:tick();assert(f.inputs==0)
    end
end)
return {passed=#names,tests=names,game_inputs=0}
