-- World lifetime guards, tested without invoking live DF state-change handlers.
local source=...
local hooks={}
local env=setmetatable({SC_WORLD_LOADED=1,SC_WORLD_UNLOADED=2,SC_MAP_LOADED=3,SC_MAP_UNLOADED=4,dfhack={onStateChange=hooks,
    internal={md5=function()return '0123456789abcdef0123456789abcdef' end},getTickCount=function()return 100 end}},
    {__index=_ENV})
local m=assert(load(source,'session-fixture','t',env))()
local s=m.open()
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('source refresh keeps session identity and historical receipts',function()
    local epoch=s.world_epoch
    s.dispatches.old={world_epoch=epoch,dispatch={outcome='completed'}}
    assert(m.open()==s and s.world_epoch==epoch and m.matches(s.dispatches.old,s))
    assert(not m.matches({},s)) -- Legacy progress has no verified lifetime.
end)
test('local map reload events do not invalidate travel progress',function()
    local epoch=s.world_epoch
    local generation=s.map_generation
    hooks.df_llm_session(4)
    hooks.df_llm_session(3)
    assert(s.world_epoch==epoch and m.matches(s.dispatches.old,s))
    assert(s.map_generation==generation+2)
end)
test('manual save renaming retains progress but actor or world replacement revokes it',function()
    local record={world_epoch=s.world_epoch,save='before-save',adventurer_id=10}
    assert(not m.resume_reason(record,s,{save='after-save',adventurer_id=10}))
    assert(m.resume_reason(record,s,{save='before-save',adventurer_id=11}))
    assert(m.resume_reason({save='before-save',adventurer_id=10},s,{save='before-save',adventurer_id=10}))
end)
test('world reload revokes live leases and old progress, retaining diagnostics',function()
    s.active_dispatch='old';s.pending='input'
    env.dfhack.df_llm_choices={serial=12,entries={old='c1'},order={'old'}}
    hooks.df_llm_session(2)
    assert(not m.matches(s.dispatches.old,s) and s.dispatches.old.world_changed)
    assert(s.dispatches.old.interrupted and s.dispatches.old.dispatch.outcome=='completed')
    assert(not s.active_dispatch and not s.pending)
    assert(env.dfhack.df_llm_choices.serial==12 and next(env.dfhack.df_llm_choices.entries)==nil)
    local epoch=s.world_epoch;hooks.df_llm_session(1)
    assert(s.world_epoch~=epoch and not m.matches(s.dispatches.old,s))
end)
test('session index is bounded and never reads persistent storage',function()
    env.dfhack.persistent=setmetatable({},{__index=function()error('Persistent read')end})
    s.dispatch_order={'older','latest'}
    s.dispatches.older={world_epoch='old',dispatch={outcome='completed'}}
    s.dispatches.latest={world_epoch=s.world_epoch,workflow={action={type='walk_to'}}}
    s.active_dispatch='latest'
    local out=m.describe(s,1)
    assert(out.total==2 and out.truncated and #out.dispatches==1)
    assert(out.dispatches[1].id=='latest' and out.dispatches[1].active)
    assert(not out.dispatches[1].world_changed)
    assert(m.lookup(s,'missing')==nil)
    assert(m.describe(s,2).dispatches[2].world_changed)
end)
return {passed=#names,tests=names,game_inputs=0}
