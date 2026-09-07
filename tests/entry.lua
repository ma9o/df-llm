-- The actual script entry with a dependency loader that poisons omitted readers.
local source=...
local modules,requests,output={}, {}, nil
local forbid={}
local package_path='Z:/fixture with spaces/dfharness/'
local env=setmetatable({dfhack_flags={module=true},print=function(value)output=value end,
    dfhack={reqscript=function(name)
        assert(name:sub(1,#package_path)==package_path,'Dependency escaped the explicit package path')
        name='dfharness/'..name:sub(#package_path+1)
        assert(not forbid[name],'Unrequested native profile loaded: '..name)
        modules[name]=true
        if name=='dfharness/bridge' then return {factory=function(req,readers)
            requests[#requests+1]=req
            assert(type(readers.health)=='function' and type(readers.progress)=='function')
            return {ok=true,result={op=req.op,zero=req.zero,enabled=req.enabled}}
        end}end
        return {factory=function()error('Fixture should not execute native readers')end}
    end}}, {__index=_ENV})
assert(load(source,'entry-fixture','t',env))()
local function request(payload)return env.request(payload,package_path)end
local tests={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));tests[#tests+1]=name end

test('routine requests load the burden helper without full profiles or a HUD scanner',function()
    forbid={['dfharness/character']=true,['dfharness/character_details']=true,['dfharness/unit']=true,['dfharness/hud']=true}
    request('{"op":"observe","zero":0,"enabled":false}')
    assert(requests[1].zero==0 and requests[1].enabled==false)
    assert(output:find('__DFLLM_JSON__',1,true)==1 and modules['dfharness/character_calculations'])
    assert(modules['dfharness/burden'])
end)
test('character profiles are available for their explicit queries',function()
    forbid={};modules={};request('{"op":"character_brief"}')
    assert(modules['dfharness/character'] and modules['dfharness/character_details'])
    assert(not modules['dfharness/unit'])
end)
test('receipt progression does not load the full character details reader',function()
    forbid={['dfharness/character_details']=true,['dfharness/unit']=true}
    modules={};request('{"op":"poll","observe":true,"character_progress":true}')
    assert(modules['dfharness/character'] and not modules['dfharness/character_details'])
    forbid={}
end)
test('each request has its own payload and reader table',function()
    modules={};request('{"op":"unit","unit_id":42}')
    assert(modules['dfharness/unit'] and not modules['dfharness/character'])
    assert(requests[1].op=='observe' and requests[#requests].unit_id==42)
end)
test('missing or relative package roots cannot fall through to script discovery',function()
    for _,root in ipairs({'','dfharness/','Z:dfharness/','/dfharness'})do
        assert(not pcall(env.request,'{"op":"observe"}',root))
    end
    assert(not pcall(env.request,'{"op":"observe"}'))
end)
return {passed=#tests,tests=tests,game_inputs=0}
