--@ module=true
--luacheck: globals factory
local function build(...)
-- Bounded, cursor-based native report reads. No input and no retained pointers.
local h=...
return function(reports,after,limit,world_replaced)
    assert(after==nil or (type(after)=='number' and after==math.floor(after) and after>=-1),
        'reports_after must be an integer >= -1')
    limit=limit or (after~=nil and 4096 or 80)
    assert(type(limit)=='number' and limit==math.floor(limit) and limit>=1 and limit<=4096,
        'report_limit must be an integer in [1, 4096]')
    -- The old world's report cursor has no meaning after a load. Return a new
    -- baseline, not the newly loaded save's entire historic conversation log.
    if world_replaced then after=nil;limit=1 end
    local total=#reports
    local latest=total>0 and reports[total-1].id or -1
    local reset=after~=nil and after>latest
    local first=math.max(0,total-limit)
    if after~=nil then
        -- Reports are appended in increasing native ID order. Read the first
        -- requested page, not a tail that could silently drop a busy interval.
        local lo,hi=0,total
        while lo<hi do
            local mid=math.floor((lo+hi)/2)
            if reports[mid].id>(reset and -1 or after) then hi=mid else lo=mid+1 end
        end
        first=lo
    end
    local last=math.min(total,first+limit)
    local out={reports=h.array(),report_cursor=latest,reports_more=last<total,
        reports_truncated=after==nil and first or 0,reports_total=total}
    if world_replaced then out.report_scope='world_replacement_baseline' end
    if reset then out.report_cursor_reset=true end
    if after~=nil then out.reports_after=after end
    for i=first,last-1 do
        local r=reports[i]
        out.reports[#out.reports+1]={id=r.id,text=h.text(r.text),
            speaker_id=r.speaker_id,activity_id=r.activity_id,activity_event_id=r.activity_event_id,
            type=df.announcement_type[r.type],year=r.year,year_tick=r.time}
    end
    if out.reports_more then out.next_report_cursor=reports[last-1].id end
    return out
end

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
