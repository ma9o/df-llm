local source=...
local names={}
local function test(name,fn)local ok,e=pcall(fn);assert(ok,name..': '..tostring(e));names[#names+1]=name end
local function fixture()
    local f={reports={},registrations={},state={},eventful={onReport={},eventType={REPORT=12}}}
    f.eventful.enableEvent=function(kind,freq)f.registrations[#f.registrations+1]={kind,freq}end
    local vector=setmetatable({}, {__len=function()return #f.reports end,
        __index=function(_,i)return f.reports[i+1]end})
    local env=setmetatable({SC_WORLD_UNLOADED=1,SC_MAP_UNLOADED=2,
        df={global={world={status={reports=vector}}},announcement_type={[9]='COMBAT_STRIKE_DETAILS'},
            report={find=function(id)
                for _,r in ipairs(f.reports)do if r.id==id then return r end end
            end}},
        dfhack={onStateChange=f.state},require=function(name)
            assert(name=='plugins.eventful');assert(not f.missing,'Plugin unavailable');return f.eventful
        end},{__index=_ENV})
    f.api=assert(load(source,'report-events-fixture','t',env))()
    function f:add(id,emit)
        local r={id=id,type=9,text='report '..id};self.reports[#self.reports+1]=r
        if emit then for _,fn in pairs(self.eventful.onReport)do fn(id)end end
        return r
    end
    return f
end
test('capability discovery neither registers events nor enables their polling',function()
    local f=fixture();assert(f.api.support().available)
    assert(#f.registrations==0 and not next(f.eventful.onReport))
end)
test('eventful uses one simulation tick and copies records once in ID order',function()
    local f=fixture();local s=f.api.watch(-1,10)
    assert(f.registrations[1][1]==12 and f.registrations[1][2]==1)
    local r=f:add(5,true);f:add(8,true);r.text='mutated native record'
    local list=s:window(-1)
    assert(#list==2 and list[1].id==8 and list[2].text=='report 5')
    assert(list[1].type=='COMBAT_STRIKE_DETAILS' and s.stats.events==2 and s.stats.catchup==0)
    assert(#s:window(8)==0 and #s:window(5)==1)
end)
test('synchronous catch-up covers callback ordering without duplicate reports',function()
    local f=fixture();local s=f.api.watch(-1,10);f:add(0,false)
    assert(#s:window(-1)==1 and s.stats.catchup==1)
    for _,fn in pairs(f.eventful.onReport)do fn(0)end
    assert(#s:window(-1)==1 and s.stats.events==0)
    f:add(1,true);assert(#s:window(-1)==2)
end)
test('plugin absence and lost registrations retain the native cursor fallback',function()
    local f=fixture();f.missing=true;local s=f.api.watch(-1,10)
    assert(s.stats.source=='native_report_cursor' and s.stats.fallback_reason)
    f:add(0,false);assert(s:window(-1)[1].id==0)
    f=fixture();s=f.api.watch(-1,10);f.eventful.onReport={}
    f:add(1,false);assert(s:window(-1)[1].id==1 and s.stats.catchup==1)
end)
test('overflow and cursor reset cannot silently become complete evidence',function()
    local f=fixture();local s=f.api.watch(-1,1);f:add(0,true);f:add(1,true)
    local list,reason=s:window(-1);assert(not list and reason:find('exceeds',1,true))
    f=fixture();s=f.api.watch(-1,10);f:add(5,true);f.reports={}
    list,reason=s:window(5);assert(not list and reason:find('reset',1,true))
end)
test('closing an observer only removes its own core callbacks',function()
    local f=fixture();local a,b=f.api.watch(-1,10),f.api.watch(-1,10)
    a:close();a:close();f:add(1,true)
    assert(a.stats.events==0 and b.stats.events==1 and a.closed)
    b:close();assert(not next(f.eventful.onReport) and not next(f.state))
end)
test('world and local map replacement invalidate and remove subscriptions',function()
    for _,code in ipairs({1,2})do
        local f=fixture();local s=f.api.watch(-1,10)
        for _,fn in pairs(f.state)do fn(code)end
        assert(s.closed and s.reason and not s:window(-1))
        assert(not next(f.eventful.onReport) and not next(f.state))
    end
end)
return {passed=#names,tests=names,game_inputs=0}
