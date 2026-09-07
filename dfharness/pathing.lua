--@ module=true
--luacheck: globals factory
local function build(h)
-- Submit the game's AdventureAutomove command. DF computes and follows the path.
-- Pausing on a watch-data change leaves policy evaluation to the shared controller
-- engine. No direction selection, pathfinder, threat model or action timers here.
local M={}
local function pos(p)return {x=p.x,y=p.y,z=p.z}end
local function absolute(p)
    local map=df.global.world.map
    return {x=p.x+map.region_x*48,y=p.y+map.region_y*48,z=p.z+map.region_z}
end
local function equal(a,b)return a.x==b.x and a.y==b.y and a.z==b.z end
function M.state()
    local ok,out=pcall(function()
        assert(type(dfhack.units.setPathGoal)=='function','DFHack setPathGoal is unavailable')
        assert(type(df.adventure_movement_pathst.new)=='function','Native movement command is unavailable')
        assert(type(df.unit_path_goal.AdventureAutomove)=='number','Native automove goal is unavailable')
        assert(type(df.dungeon_control_state.CONTINUE)=='number','Native continuation is unavailable')
        assert(type(df.unit_path_goal.None)=='number' and type(df.dungeon_control_state.PROMPT)=='number',
            'Native goal cancellation is unavailable')
        assert(type(dfhack.maps.canWalkBetween)=='function' and type(dfhack.maps.isTileVisible)=='function'
            and type(dfhack.maps.getTileSize)=='function','DFHack native reachability reads are unavailable')
        local u=assert(dfhack.world.getAdventurer(),'Local adventurer is unavailable')
        return {available=true,goal=df.unit_path_goal[u.path.goal],destination=pos(u.path.dest),
            control=df.dungeon_control_state[u.dungeon_control]}
    end)
    return ok and out or {available=false,reason=tostring(out):sub(1,240)}
end
function M.prepare(action,request)
    local state=M.state();assert(state.available,state.reason)
    assert(state.goal=='None','Another native path goal is already active')
    local u=assert(dfhack.world.getAdventurer())
    local target=action.destination
    local x,y,z=dfhack.maps.getTileSize()
    for k,limit in pairs({x=x,y=y,z=z})do
        assert(type(target[k])=='number' and target[k]%1==0 and target[k]>=0 and target[k]<limit,
            'Native path destination is outside the loaded map')
    end
    local radius=action.arrival_radius or 0
    assert(type(radius)=='number' and radius%1==0 and radius>=0 and radius<=48,'Invalid native arrival radius')
    -- Select an allowed endpoint, never a route. DF's connected groups decide
    -- reachability, and DF's pathfinder handles every tile between the endpoints.
    -- This also permits approaching a unit, wall or liquid without occupying it.
    local goal,best
    for gy=math.max(0,target.y-radius),math.min(y-1,target.y+radius)do
        for gx=math.max(0,target.x-radius),math.min(x-1,target.x+radius)do
            local candidate={x=gx,y=gy,z=target.z}
            if dfhack.maps.isTileVisible(gx,gy,target.z) and dfhack.maps.canWalkBetween(u.pos,candidate)then
                local distance=(gx-u.pos.x)^2+(gy-u.pos.y)^2
                if not best or distance<best then goal=candidate;best=distance end
            end
        end
    end
    assert(goal,'No visible endpoint within the arrival radius has a DFHack walkable connection; the native cache may be stale')
    local policy=request.path_execution
    assert(type(policy)=='table' and (policy.mode=='step' or policy.mode=='complete'),'Missing path execution mode')
    assert(type(request.path_timeout_ms)=='number' and request.path_timeout_ms>0
        and request.path_timeout_ms<=300000,'Invalid native path deadline')
    return {kind='walk',available=true,phase='prepared',unit_id=u.id,
        destination=absolute(goal),target=absolute(target),arrival_radius=radius,
        source=absolute(u.pos),adapter='native_path'}
end
function M.start(e,_,request,session,receipt)
    local world_epoch=session.world_epoch
    e.world_epoch=world_epoch
    local started=dfhack.getTickCount()
    local deadline=started+request.path_timeout_ms
    local rules=request.path_execution.interrupt_on or {}
    local types={};for _,name in ipairs(rules.report_types or {})do types[name]=true end
    local reports=df.global.world.status.reports
    local cursor=#reports>0 and reports[#reports-1].id or -1
    local stream
    local function watch()
        local s={mode='adventure',map_loaded=dfhack.isMapLoaded(),adventurer_id=e.unit_id}
        local r={status=s}
        local fields={}
        if rules.blood_loss then fields[#fields+1]='blood_count' end
        if rules.new_wounds then fields[#fields+1]='wounds' end
        if #fields>0 then r.adventurer=h.health.player(s,fields) end
        if rules.new_visible_units or #(rules.visible_unit_ids or {})>0 then
            r.map=h.movement.visible_units(s.map_loaded)
        end
        if request.watch_units then r.watched_units=h.health.read(request.watch_units,s.map_loaded) end
        if next(types)then
            r.reports={}
            -- The initial baseline shares the cursor's suspended core call.
            -- Subsequent reads use the adapter's bounded, copied report window.
            if stream then
                local list,err=stream:window(cursor);assert(list,err)
                for _,report in ipairs(list)do
                    if types[report.type]then r.reports[#r.reports+1]={id=report.id,type=report.type}end
                end
            end
        end
        return r
    end
    local baseline=watch()
    stream=next(types) and h.report_events.watch(cursor,4096)
    if stream then e.report_observer=stream.stats end
    local function owned(u)
        return u.path.goal==df.unit_path_goal.AdventureAutomove and equal(absolute(u.path.dest),e.destination)
    end
    local function halt(phase,why,u,sample)
        -- Cancel only this goal via DFHack's API. A Move already in flight is
        -- allowed to settle; neither its destination nor its timer is edited.
        if u and owned(u)then
            dfhack.units.setPathGoal(u,pos(u.pos),df.unit_path_goal.None)
            if u.dungeon_control==df.dungeon_control_state.CONTINUE then
                u.dungeon_control=df.dungeon_control_state.PROMPT
            end
        end
        e.phase=phase;e.reason=why;e.watch_view=sample
        if stream then stream:close()end
        if u then e.position=absolute(u.pos)end
        receipt.settled=true
    end
    local guarded_sample
    local function sample()
        if session.world_epoch~=world_epoch or not dfhack.isMapLoaded()then
            halt('unavailable','World or local map changed');return
        end
        local u=dfhack.world.getAdventurer()
        if not u or u.id~=e.unit_id then halt('unavailable','Adventurer changed');return end
        local parent=session.dispatches[request.parent_dispatch]
        if not parent or parent.interrupted or session.active_dispatch~=request.parent_dispatch then
            halt('paused','dispatch_interrupted',u);return
        end
        local current=watch()
        if not h.same(baseline,current)then halt('paused','watch_changed',u,current);return end
        if dfhack.getTickCount()>=deadline then halt('paused','deadline',u);return end
        local control=df.global.adventure.player_control_state
        if control==df.adventure_game_loop_type.TAKING_TOO_LONG_INPUT then
            halt('paused','interface',u);return
        end
        local focus=dfhack.gui.getCurFocus(true)
        if #focus~=1 or focus[1]~='dungeonmode/Default'
            or df.global.world.status.temp_flag.adv_showing_announcements
            or #df.global.world.status.popups>0 then
            halt('paused','interface',u);return
        end
        local here=absolute(u.pos)
        local target=e.target
        local arrived=here.z==target.z and math.max(math.abs(here.x-target.x),math.abs(here.y-target.y))<=e.arrival_radius
        if arrived and control==df.adventure_game_loop_type.TAKING_INPUT then
            halt('completed','Destination reached',u);return
        end
        if request.path_execution.mode=='step' and not equal(here,e.source)
            and control==df.adventure_game_loop_type.TAKING_INPUT then
            halt('paused','incremental_boundary',u);return
        end
        if not owned(u)then
            halt('blocked','Native path ended or was replaced before arrival',nil);return
        end
        assert(dfhack.timeout(1,'frames',guarded_sample),'Native path watcher could not be scheduled')
    end
    local function failed(err)
        local live=session.world_epoch==world_epoch and dfhack.isMapLoaded() and dfhack.world.getAdventurer()
        halt('unavailable',tostring(err):sub(1,240),live and live.id==e.unit_id and live or nil)
    end
    guarded_sample=function()
        local ok,err=pcall(sample)
        if not ok then failed(err)end
    end
    local u=assert(dfhack.world.getAdventurer())
    local command=df.adventure_movement_pathst:new()
    local ok,err=pcall(function()
        local map=df.global.world.map
        local goal={x=e.destination.x-map.region_x*48,y=e.destination.y-map.region_y*48,z=e.destination.z-map.region_z}
        command.source:assign(u.pos);command.dest:assign(goal);command.vpz=goal.z
        command.is_acrobatic=false;command.is_down_through_hatch=false
        command.option_list_context=df.adventure_interface_option_list_context_type.DIRECT_CLICK_MOVE_ONLY
        assert(command:hasRealize(),'Native path command cannot be realized')
        command:doRealize()
    end)
    command:delete()
    if not ok then failed(err);error(err)end
    ok,err=pcall(function()
        assert(owned(u),'Native handler did not accept the requested path')
        u.dungeon_control=request.path_execution.mode=='complete'
            and df.dungeon_control_state.CONTINUE or df.dungeon_control_state.PROMPT
        e.phase='running'
        h.input('A_SHORT_WAIT')
        sample()
    end)
    if not ok then failed(err);error(err)end
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
