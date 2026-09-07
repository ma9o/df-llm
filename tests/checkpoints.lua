-- Save/reload fixtures use a fake world store; never save or reload the live game.
local source,wire_source=...
local json=require('json')
local wire=assert(load(wire_source))()
local store={}
local broken=false
local env=setmetatable({dfhack={isWorldLoaded=function()return true end,persistent={
    getWorldData=function(key)return store[key] and json.decode(store[key])end,
    saveWorldData=function(key,value)
        assert(not broken,'Simulated storage failure')
        store[key]=json.encode(value)
    end}}},{__index=_ENV})
local m=assert(load(source,'checkpoint-fixture','t',env))(wire)
local function session(epoch)return {world_epoch=epoch or 'first',dispatches={}}end
local function record()
    return {request='intent',adventurer_id=0,save='checkpoint',
        workflow={action={type='sequence'},context={stage_index=1,
            stages={{action={type='wait'},context={pending='past stage'}},{action={type='wait'},context={}}},
            results={{outcome='completed'}}},
            extra=wire.null,empty_array=require('json.internal'):newArray{},empty_object=require('json.internal'):newObject{}},
        dispatch={outcome='limit_reached',events={{id=0,text='Observed reply'}}},compact={outcome='limit_reached'}}
end
local tests={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));tests[#tests+1]=name end
local saved,active_saved
test('world store preserves exact JSON types and a verified fresh-stage checkpoint',function()
    local s=session();local r=record()
    assert(m.begin(s,'a',r))
    active_saved=wire.clone(store)
    assert(m.finish(s,'a',r,{checkpoint_guard='p1:native'},{settled=true}))
    saved=wire.clone(store)
    local restored=session('restarted');restored.dispatches.a={workflow='newer unsaved progress'}
    assert(m.open(restored).available and not restored.dispatches.a)
    local value=m.lookup(restored,'a')
    assert(value.resume_guard=='p1:native' and not value.restore_reason and value.restored_epoch=='restarted')
    assert(value.workflow.context.stage_index==1 and value.adventurer_id==0)
    assert(value.workflow.extra==wire.null)
    assert(wire.encode(value.workflow.empty_array)=='[]' and wire.encode(value.workflow.empty_object)=='{}')
    assert(value.dispatch.events[1].text=='Observed reply' and not value.view and not value.last_action_id)
end)
test('a game save during an active dispatch retains diagnostics without a resume lease',function()
    store=wire.clone(active_saved)
    local s=session('active-reload');local r=m.lookup(s,'a')
    assert(r.restore_reason:find('active',1,true) and not r.resume_guard and not r.workflow)
    assert(m.describe(s,20).dispatches[1].resumable==false)
end)
test('older saves restore their own progress and resumed predecessors remain superseded',function()
    store=wire.clone(saved)
    local s=session('new');m.lookup(s,'a')
    local r=record();assert(m.begin(s,'b',r,'a'))
    local active=wire.clone(store)
    local loaded=session('again');local old=m.lookup(loaded,'a')
    assert(old.resumed_by=='b' and m.lookup(loaded,'b').restore_reason)
    store=wire.clone(saved)
    loaded=session('rewind');old=m.lookup(loaded,'a')
    assert(not old.resumed_by and old.workflow.context.stage_index==1)
    store=active
end)
test('pending markers, unfinished input, missing guards and completed objectives cannot resume on reload',function()
    for _,kind in ipairs({'pending','input','guard','completed'})do
        store={};local s=session();local r=record()
        local view,receipt={checkpoint_guard='p1:native'},{settled=true}
        if kind=='pending' then r.workflow.context.stages[2].context.pending={effect='n2:old'}
        elseif kind=='input' then receipt.settled=false
        elseif kind=='guard' then view.checkpoint_guard=nil
        else r.dispatch.outcome='completed' end
        assert(m.begin(s,kind,r) and m.finish(s,kind,r,view,receipt))
        local restored=m.lookup(session('new'),kind)
        assert(restored.restore_reason and not restored.resume_guard and restored.workflow)
    end
end)
test('oversized diagnostics and broken storage never advertise a recoverable checkpoint',function()
    store={};local s=session();local r=record();r.workflow.large=string.rep('x',140000)
    assert(m.begin(s,'big',r) and m.finish(s,'big',r,{checkpoint_guard='p1:native'},nil))
    local restored=m.lookup(session('new'),'big')
    assert(restored.restore_reason:find('byte limit',1,true) and not restored.workflow and not restored.resume_guard)
    broken=true
    local ok,reason=m.begin(s,'bad',record());assert(not ok and reason)
    assert(not m.describe(s,20).available)
    broken=false
end)
test('fixed slots bound the saved record count and readers can limit the returned index',function()
    store={};local s=session()
    for i=1,131 do assert(m.begin(s,'dispatch-'..i,record()))end
    local count=0;for _ in pairs(store)do count=count+1 end
    assert(count==129)
    local r=m.describe(session('new'),3)
    assert(#r.dispatches==3 and r.dispatches[1].id=='dispatch-131')
    assert(r.total==128 and r.truncated)
    assert(not m.lookup(session('new'),'dispatch-1'))
end)
test('corrupt record failures remain explicit and lazy restoration preserves memory bounds',function()
    store=wire.clone(saved)
    local s=session('new');m.open(s)
    store['df-llm/session/v1/0']=json.encode('bad checkpoint')
    local r=m.lookup(s,'a')
    assert(r.restore_reason and not r.resume_guard)
    local meta=m.describe(s,20).dispatches[1]
    assert(not meta.resumable and meta.reason)
    store=wire.clone(saved);s=session('new')
    s.dispatch_order={}
    for i=1,128 do s.dispatch_order[i]='old-'..i;s.dispatches['old-'..i]={}end
    assert(m.lookup(s,'a').resume_guard and #s.dispatch_order==128 and s.dispatches['old-1']==nil)
end)
return {passed=#tests,tests=tests,game_inputs=0}
