--@ module=true
--luacheck: globals factory
local function build(...)
-- Processing samples are deliberately not snapshots or input guards.
-- Read only reports and the controller's requested factual predicates.
local h=...
return function(status,request,replaced)
    local out={schema_version=1,status={}}
    for _,k in ipairs({'ready_for_input','world_epoch','local_map_epoch','mode','map_loaded',
        'adventurer_id','world_frame','year','year_tick','turn_phase'})do out.status[k]=status[k] end
    local watch=request.progress_watch or {}
    assert(type(watch)=='table','progress_watch must be an object')
    local fields=h.array()
    for k,v in pairs(watch)do
        assert((k=='blood_count' or k=='wounds' or k=='visible_units') and type(v)=='boolean',
            'Unknown progress predicate or invalid flag')
    end
    for _,k in ipairs({'blood_count','wounds'})do if watch[k] then fields[#fields+1]=k end end
    if #fields>0 then out.adventurer=h.health.player(status,fields) end
    if watch.visible_units then
        out.map=h.movement.visible_units(status.mode=='adventure' and status.map_loaded)
    end
    if request.watch_units then
        out.watched_units=h.health.read(request.watch_units,status.mode=='adventure' and status.map_loaded)
    end
    if status.mode=='adventure' then
        for k,v in pairs(h.reports(df.global.world.status.reports,request.reports_after,
            request.report_limit,replaced))do out[k]=v end
    end
    return out
end

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
