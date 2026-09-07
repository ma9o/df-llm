-- Processing reads are independent from menus, item graphs and snapshot guards.
local source=...
local calls={}
local forbidden=setmetatable({},{__index=function()error('Unrequested progress detail read')end})
local reports={{id=0,text='report'}}
local env=setmetatable({df={global={world={status={reports=reports},units=forbidden}}}}, {__index=_ENV})
local health={
    player=function(s,fields)
        calls.player=fields;assert(s.adventurer_id==0)
        return {id=0,health={blood_count=0}}
    end,
    read=function(ids,loaded)calls.units={ids=ids,loaded=loaded};return {{unit_id=ids[1],available=false}}end,
}
local movement={visible_units=function(loaded)
    calls.visible=loaded;return {units={{id=0}},units_available=true,units_truncated=false}
end}
local read=assert(load(source,'progress-fixture','t',env))({array=function()return {}end,
    health=health,movement=movement,reports=function(list,after,limit,replaced)
        assert(list==reports);calls.reports={after=after,limit=limit,replaced=replaced}
        return {reports=list,report_cursor=0,reports_more=true,next_report_cursor=0}
    end})
local status={mode='adventure',map_loaded=true,ready_for_input=false,adventurer_id=0,
    world_epoch='world',local_map_epoch='map',world_frame=0,year=100,year_tick=0,
    active_dispatch=forbidden,viewport=forbidden,travel=forbidden,modal=forbidden}
local names={}
local function test(name,fn)
    calls={};local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('unwatched pending reads retain reports without native entity scans or request echoes',function()
    local r=read(status,{reports_after=-1,report_limit=1,action=forbidden},true)
    assert(not calls.player and not calls.units and calls.visible==nil)
    assert(calls.reports.after==-1 and calls.reports.limit==1 and calls.reports.replaced)
    assert(r.reports[1].id==0 and r.reports_more and r.report_cursor==0 and r.next_report_cursor==0)
    assert(not r.map and not r.adventurer and not r.state_id and not r.effect_id and not r.ui)
    assert(not r.status.active_dispatch and not r.status.viewport and not r.status.travel and not r.status.modal)
    assert(r.status.year_tick==0 and r.status.ready_for_input==false and r.status.world_epoch=='world')
end)
test('predicates request only their own bounded native data',function()
    local r=read(status,{progress_watch={blood_count=true,wounds=false,visible_units=true},watch_units={2}})
    assert(#calls.player==1 and calls.player[1]=='blood_count' and calls.visible==true)
    assert(calls.units.ids[1]==2 and calls.units.loaded)
    assert(r.adventurer.health.blood_count==0 and r.watched_units[1].available==false and r.map.units[1].id==0)
end)
test('menu transitions neither enumerate units nor replay world reports',function()
    local r=read({mode='menus',map_loaded=false,ready_for_input=false},{watch_units={2}})
    assert(not calls.reports and not calls.player and calls.visible==nil and calls.units.loaded==false)
    assert(not r.reports and r.schema_version==1)
end)
test('invalid progress predicates cannot be silently ignored',function()
    for _,watch in ipairs({{unknown=true},{blood_count=1},{wounds='true'}})do
        assert(not pcall(read,status,{progress_watch=watch}))
    end
end)
return {passed=#names,tests=names,game_inputs=0}
