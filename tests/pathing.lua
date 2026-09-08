local source=...
local names={}
local function test(name,fn)local ok,e=pcall(fn);assert(ok,name..': '..tostring(e));names[#names+1]=name end
local function fixture()
    local f={now=0,queue={},inputs={},cancels=0,allocations=0,focus={'dungeonmode/Default'},blood=100,visible={1},report_window={},closed=0}
    local u={id=1,pos={x=1,y=1,z=0},path={dest={x=-30000,y=-30000,z=-30000},goal=0},dungeon_control=0,
        flags1={rider=false},relationship_ids={[9]=-1}}
    f.unit=u
    f.mount={id=5,pos={x=1,y=1,z=0},path={dest={x=-30000,y=-30000,z=-30000},goal=0}}
    local function coord()
        return {assign=function(self,p)assert(not getmetatable(p));self.x=p.x;self.y=p.y;self.z=p.z end}
    end
    local function same(a,b)
        if type(a)~=type(b)then return false end
        if type(a)~='table'then return a==b end
        for k,v in pairs(a)do if not same(v,b[k])then return false end end
        for k in pairs(b)do if a[k]==nil then return false end end
        return true
    end
    local function set_goal(unit,p,goal)
        unit.path.dest={x=p.x,y=p.y,z=p.z};unit.path.goal=goal
        if goal==0 then f.cancels=f.cancels+1 end
    end
    local command={new=function()
        f.allocations=f.allocations+1
        return {source=coord(),dest=coord(),hasRealize=function()return true end,
            doRealize=function(self)if u.flags1.rider then set_goal(f.mount,self.dest,2)else set_goal(u,self.dest,1)end end,
            delete=function()f.allocations=f.allocations-1 end}
    end}
    local game={player_control_state=0}
    local env=setmetatable({df={global={world={map={region_x=0,region_y=0,region_z=0},
        status={reports={},popups={},temp_flag={adv_showing_announcements=false}}},adventure=game},
        adventure_movement_pathst=command,unit_path_goal={[0]='None',[1]='AdventureAutomove',[2]='FollowCommand',None=0,AdventureAutomove=1,FollowCommand=2},
        unit_relationship_type={RiderMount=9},unit={find=function(id)return id==5 and f.mount or nil end},
        dungeon_control_state={[0]='PROMPT',[1]='CONTINUE',PROMPT=0,CONTINUE=1},
        adventure_game_loop_type={TAKING_INPUT=0,TAKING_TOO_LONG_INPUT=2},
        adventure_interface_option_list_context_type={DIRECT_CLICK_MOVE_ONLY=0}},
        dfhack={units={setPathGoal=set_goal},world={getAdventurer=function()return u end},
            isMapLoaded=function()return true end,getTickCount=function()return f.now end,
            gui={getCurFocus=function()return f.focus end},
            maps={getTileSize=function()return 100,100,10 end,
                isTileVisible=function(x,y)return not f.hidden and not (f.hidden_tiles and f.hidden_tiles[x..','..y])end,
                canWalkBetween=function(_,p)
                    assert(not getmetatable(p));return not f.unreachable and not (f.blocked and p.x==8 and p.y==1)
                end},
            timeout=function(_,_,fn)
                if f.fail_schedule then return nil end
                f.queue[#f.queue+1]=fn;return #f.queue
            end}}, {__index=_ENV})
    f.api=assert(load(source,'native-path-fixture','t',env))({same=same,
        report_events={watch=function(_,limit)
            assert(limit==4096)
            return {stats={},window=function()return f.report_window end,
                close=function()f.closed=f.closed+1 end}
        end},
        input=function(key)f.inputs[#f.inputs+1]=key end,
        health={player=function()return {health={blood_count=f.blood}}end},
        movement={visible_units=function()
            local units={};for _,id in ipairs(f.visible)do units[#units+1]={id=id}end
            return {units=units,units_available=true,units_truncated=false}
        end}})
    f.map=env.df.global.world.map
    f.session={world_epoch='world',active_dispatch='dispatch',dispatches={dispatch={}}}
    f.request={parent_dispatch='dispatch',path_execution={mode='complete',interrupt_on={}},path_timeout_ms=1000}
    f.action={destination=setmetatable({x=8,y=1,z=0},{})}
    function f:start()
        self.e=self.api.prepare(self.action,self.request);self.receipt={settled=false}
        self.api.start(self.e,self.action,self.request,self.session,self.receipt)
    end
    function f:tick()local fn=table.remove(self.queue,1);assert(fn);fn()end
    return f
end
test('native path command and completion use named interfaces with one input',function()
    local f=fixture();f:start()
    assert(f.unit.pos.x==1 and f.unit.path.dest.x==8 and f.unit.dungeon_control==1)
    assert(#f.inputs==1 and f.inputs[1]=='A_SHORT_WAIT' and f.allocations==0)
    assert(f.e.phase=='running' and not f.receipt.settled)
    f.unit.pos.x=8;f.unit.path.goal=0;f.unit.dungeon_control=0;f:tick()
    assert(f.e.phase=='completed' and f.receipt.settled and f.cancels==0)
end)
test('eventful report windows retain named types and close on a route interruption',function()
    local f=fixture();f.request.path_execution.interrupt_on={report_types={'COMBAT_STRIKE_DETAILS'}}
    f:start();f.report_window={{id=3,type='COMBAT_STRIKE_DETAILS',text='a strike'}};f:tick()
    assert(f.e.phase=='paused' and f.e.reason=='watch_changed' and f.closed==1)
    assert(f.e.watch_view.reports[1].type=='COMBAT_STRIKE_DETAILS' and f.e.watch_view.reports[1].id==3)
end)
test('watch changes pause for shared policy without inferring whether they are threats',function()
    local f=fixture();f.request.path_execution.interrupt_on={blood_loss=true};f:start()
    f.blood=120;f:tick()
    assert(f.e.phase=='paused' and f.e.reason=='watch_changed' and f.cancels==1)
    assert(f.e.watch_view.adventurer.health.blood_count==120 and f.unit.pos.x==1)
end)
test('visible identities are watched even outside the displayed map',function()
    local f=fixture();f.request.path_execution.interrupt_on={new_visible_units=true};f:start()
    f.visible={1,99};f:tick()
    assert(f.e.phase=='paused' and #f.e.watch_view.map.units==2 and f.cancels==1)
end)
test('external interruption cancels only the submitted goal',function()
    local f=fixture();f:start();f.session.dispatches.dispatch.interrupted=true;f:tick()
    assert(f.e.reason=='dispatch_interrupted' and f.unit.path.goal==0 and f.unit.dungeon_control==0)
    f=fixture();f:start();f.unit.path.dest.x=9;f.session.dispatches.dispatch.interrupted=true;f:tick()
    assert(f.unit.path.dest.x==9 and f.cancels==0)
end)
test('world replacement revokes the watcher without touching replacement units',function()
    local f=fixture();f:start();f.session.world_epoch='replacement';f:tick()
    assert(f.e.phase=='unavailable' and f.cancels==0)
end)
test('deadline and modal pauses keep route progress without changing position',function()
    local f=fixture();f:start();f.now=1000;f:tick()
    assert(f.e.reason=='deadline' and f.unit.pos.x==1 and f.cancels==1)
    f=fixture();f:start();f.focus={'dungeonmode/Help'};f:tick()
    assert(f.e.reason=='interface' and f.cancels==1)
end)
test('step policy cancels remaining route at the next native input boundary',function()
    local f=fixture();f.request.path_execution.mode='step';f:start()
    assert(f.unit.dungeon_control==0);f.unit.pos.x=2;f:tick()
    assert(f.e.reason=='incremental_boundary' and f.unit.path.goal==0 and f.unit.pos.x==2)
end)
test('unreachable destinations fail before input or allocation',function()
    local f=fixture();f.unreachable=true;assert(not pcall(function()f:start()end))
    assert(#f.inputs==0 and f.allocations==0)
end)
test('unrevealed connected destinations are submitted to the native handler and marked',function()
    local f=fixture();f.hidden=true;f:start()
    assert(f.unit.path.dest.x==8 and f.e.endpoint_revealed==false and #f.inputs==1)
    f=fixture();f:start();assert(f.e.endpoint_revealed==true)
end)
test('an absolute destination is converted against the live map origin, not the stale local target',function()
    local f=fixture();f.action.absolute_destination={x=57,y=1,z=0};f:start()
    assert(f.unit.path.dest.x==57 and f.e.target.x==57)
    f=fixture();f.action.absolute_destination={x=57,y=1,z=0};f.map.region_x=1;f:start()
    assert(f.unit.path.dest.x==9 and f.e.target.x==57 and f.e.destination.x==57)
    f=fixture();f.action.absolute_destination={x=200,y=1,z=0}
    assert(not pcall(function()f:start()end) and #f.inputs==0 and f.allocations==0)
end)
test('arrival radius prefers a revealed reachable endpoint over a nearer hidden one',function()
    local f=fixture();f.blocked=true;f.hidden_tiles={['7,1']=true};f.action.arrival_radius=1;f:start()
    assert(f.unit.path.dest.x==7 and f.unit.path.dest.y~=1 and f.e.endpoint_revealed==true)
    f=fixture();f.blocked=true;f.hidden=true;f.action.arrival_radius=1;f:start()
    assert(f.unit.path.dest.x==7 and f.unit.path.dest.y==1 and f.e.endpoint_revealed==false)
end)
test('watcher setup failure cancels the owned goal before returning an error',function()
    local f=fixture();f.fail_schedule=true
    assert(not pcall(function()f:start()end))
    assert(f.e.phase=='unavailable' and f.receipt.settled and f.unit.path.goal==0)
    assert(f.unit.dungeon_control==0 and f.allocations==0 and #f.inputs==1)
end)
test('a stopped mount within two tiles counts as arrival and a farther stop re-issues once per progress step',function()
    local f=fixture();f.unit.flags1.rider=true;f.unit.relationship_ids[9]=5;f:start()
    f.unit.pos.x=6;f.mount.pos.x=6;f.mount.path.goal=0;f:tick()
    assert(f.e.phase=='completed' and f.e.mount_stopped_short==2)
    f=fixture();f.unit.flags1.rider=true;f.unit.relationship_ids[9]=5;f:start()
    local inputs=#f.inputs
    f.unit.pos.x=3;f.mount.pos.x=3;f.mount.path.goal=0;f.unit.dungeon_control=0
    for _=1,6 do f:tick() end -- grace expires, then one re-issue
    assert(f.mount.path.goal==2 and f.mount.path.dest.x==8 and #f.inputs==inputs+1 and f.unit.dungeon_control==1)
    assert(f.e.reissues==1 and f.e.phase=='running')
    f.mount.path.goal=0 -- stopped again without moving: no second re-issue
    for _=1,7 do if f.e.phase=='running' then f:tick() end end
    assert(f.e.phase=='blocked' and f.e.reissues==1)
end)
test('a rider owns the follow goal on the mount and arrives on the rider tile',function()
    local f=fixture();f.unit.flags1.rider=true;f.unit.relationship_ids[9]=5;f:start()
    assert(f.mount.path.goal==2 and f.mount.path.dest.x==8 and f.unit.path.goal==0 and f.e.phase=='running')
    f.unit.pos.x=8;f.mount.pos.x=8;f.mount.path.goal=0;f:tick()
    assert(f.e.phase=='completed' and f.cancels==0)
    f=fixture();f.unit.flags1.rider=true;f.unit.relationship_ids[9]=5;f:start()
    f.session.dispatches.dispatch.interrupted=true;f:tick()
    assert(f.e.reason=='dispatch_interrupted' and f.mount.path.goal==0 and f.cancels==1)
end)
test('arrival radius uses native reachable endpoints beside an unwalkable target',function()
    local f=fixture();f.blocked=true;f.action.arrival_radius=1;f:start()
    assert(f.unit.path.dest.x==7 and f.unit.path.dest.y==1 and f.e.target.x==8)
    f.unit.pos.x=7;f:tick()
    assert(f.e.phase=='completed' and f.unit.path.goal==0 and f.cancels==1)
end)
return {passed=#names,tests=names,game_inputs=0}
