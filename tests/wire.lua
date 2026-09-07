-- Exercise the real JSON representation, without touching native game state.
local source=...
local m=assert(load(source))()
local json=require('json.internal'):new{strictTypes=true}
local function read(s)return json:decode(s,nil,{null=m.null})end
local tests={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));tests[#tests+1]=name
end
test('wire round trips false zero null empty and absent values',function()
    local cases={
        {'{}','{"zero":0,"false":false,"null":null,"array":[],"object":{}}'},
        {'{"null":null,"array":[],"object":{}}','{"null":false,"array":{},"object":[]}'},
        {'{"old":1,"nested":{"value":false}}','{"nested":{"value":0}}'},
        {'[{"id":1,"value":2},{"id":2,"value":3}]','[{"id":1,"value":2},{"id":2,"value":4},null]'},
        {'[0,1,2]','[0]'}, {'[null,false,0]','[]'}, {'null','{}'}, {'[]','null'}}
    for _,pair in ipairs(cases)do
        local a,b=read(pair[1]),read(pair[2]);local before=m.encode(a)
        local applied=m.apply(a,read(m.encode(m.delta(a,b))))
        assert(m.encode(applied)==m.encode(b),pair[1]..' -> '..pair[2])
        assert(m.encode(a)==before,'base mutated')
    end
end)
test('wire unchanged inventory is not transmitted',function()
    local a=read('{"inventory":[{"id":1,"description":"axe","quantity":1}],"ready":false}')
    local b=m.clone(a);b.ready=true
    local d=m.delta(a,b);assert(d.fields.ready.set==true and not d.fields.inventory)
end)
test('dispatch identity ignores transport settings but preserves action policy and guard',function()
    local a=read('{"op":"begin_dispatch","request_id":"id","action":{"type":"wait"},"execution":{"mode":"step"}}')
    local b=m.clone(a);b.report_limit=1;b.result_format='compact';b.target_unit_id=1
    assert(m.intent(m.encode(a))==m.intent(b))
    b.action.type='move';assert(m.intent(a)~=m.intent(b))
    b=m.clone(a);b.expect='new';assert(m.intent(a)~=m.intent(b))
    b=m.clone(a);b.execution.mode='complete';assert(m.intent(a)~=m.intent(b))
end)
test('wire uses exact revisions and sends a full base on reader cache miss',function()
    local record={};local a=m.observe(record,'dispatch',{ready=false})
    local b=m.observe(record,'dispatch',{ready=true},a.view_ref)
    assert(a.view and b.view_delta and b.view_delta.base.revision==1 and b.view_ref.revision==2)
    local c=m.observe(record,'dispatch',{ready=true},{dispatch_id='other',revision=2})
    assert(c.view and not c.view_delta and c.view_ref.revision==3)
end)
test('wire checkpoints reject a wrong base without changing progress',function()
    local record={workflow=read('{"stage":1,"flag":false}'),workflow_revision=3}
    local request={workflow_delta={base=2,change={fields={stage={set=2}}}}}
    assert(not pcall(m.checkpoint,record,request) and record.workflow.stage==1)
    request.workflow_delta.base=3
    local result=m.checkpoint(record,request)
    assert(result.stage==2 and result.flag==false and record.workflow.stage==1)
end)
test('wire final observation cannot reference another dispatch or older revision',function()
    local record={snapshot=read('{"inventory":[1,2]}'),view_revision=3}
    assert(not pcall(m.receipt_view,record,'a',{view_ref={dispatch_id='b',revision=3}}))
    assert(not pcall(m.receipt_view,record,'a',{view_ref={dispatch_id='a',revision=2}}))
    local view=m.receipt_view(record,'a',{view_ref={dispatch_id='a',revision=3}})
    view.inventory[1]=9;assert(record.snapshot.inventory[1]==1)
end)
test('wire rejects shape errors and missing array entries',function()
    for _,pair in ipairs({{'{}','{"entries":{"0":{"set":1}}}'},
        {'[]','{"length":2,"entries":{"1":{"set":1}}}'},
        {'{}','{"fields":{"absent":{"remove":["x"]}}}'},
        {'{}','{"remove":["absent"]}'}, {'[1]','{"entries":{"2":{"set":0}}}'}})do
        assert(not pcall(m.apply,read(pair[1]),read(pair[2])))
    end
end)
return {passed=#tests,tests=tests,game_inputs=0}
