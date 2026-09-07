-- Cursor paging fixtures use plain native-shaped vectors, not the live world.
local source=...
local env=setmetatable({df={announcement_type={[0]='REGULAR_CONVERSATION'}}},{__index=_ENV})
local read=assert(load(source,'reports-fixture','t',env))({array=function()return {}end,text=function(s)return s end})
local function vector(count)
    local r=setmetatable({},{__len=function()return count end})
    for i=0,count-1 do r[i]={id=i*2,text=tostring(i),speaker_id=0,activity_id=-1,
        activity_event_id=0,type=0,year=100,time=0} end
    return r
end
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('recent default read states how much native history it omits',function()
    local r=read(vector(100))
    assert(#r.reports==80 and r.reports[1].id==40 and r.report_cursor==198)
    assert(r.reports_truncated==20 and not r.reports_more)
end)
test('cursor reads page forward without silently replacing the start with the tail',function()
    local r=read(vector(100),-1,3)
    assert(#r.reports==3 and r.reports[1].id==0 and r.next_report_cursor==4 and r.reports_more)
    local next_page=read(vector(100),r.next_report_cursor,3)
    assert(next_page.reports[1].id==6 and next_page.next_report_cursor==10)
    local after_gap=read(vector(100),7,3)
    assert(after_gap.reports[1].id==8 and after_gap.reports_truncated==0)
end)
test('empty current pages preserve cursor and zero native fields',function()
    local r=read(vector(1),-1)
    assert(r.reports[1].speaker_id==0 and r.reports[1].year_tick==0)
    r=read(vector(1),0);assert(#r.reports==0 and r.report_cursor==0 and not r.reports_more)
    r=read(vector(0),-1);assert(#r.reports==0 and r.report_cursor==-1 and not r.report_cursor_reset)
end)
test('report cursor reset is explicit and does not hide the new history',function()
    local r=read(vector(3),500)
    assert(r.report_cursor_reset and #r.reports==3 and r.reports[1].id==0)
end)
test('world replacement reads one baseline without replaying old save history',function()
    local r=read(vector(10000),-1,nil,true)
    assert(#r.reports==1 and r.reports[1].id==19998 and r.report_cursor==19998)
    assert(r.reports_truncated==9999 and not r.reports_more and not r.report_cursor_reset)
    assert(r.report_scope=='world_replacement_baseline')
    r=read(vector(0),500,nil,true)
    assert(#r.reports==0 and r.report_cursor==-1 and not r.report_cursor_reset)
end)
test('malformed and unbounded read requests are rejected',function()
    for _,limit in ipairs({0,4097,1.5}) do assert(not pcall(read,vector(1),0,limit)) end
    assert(not pcall(read,vector(1),-2))
end)
return {passed=#names,tests=names,game_inputs=0}
