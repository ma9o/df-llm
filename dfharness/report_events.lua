--@ module=true
--luacheck: globals factory
local function build()
-- Scoped eventful report windows. Only copied scalars survive a callback.
-- A synchronous cursor catch-up covers callback ordering, plugin reloads and
-- unavailable plugins. Combat attribution remains the caller's responsibility.
local M={}
local function plugin()
    local e=require('plugins.eventful')
    assert(type(e.enableEvent)=='function' and e.onReport and type(e.eventType.REPORT)=='number',
        'eventful.onReport is unavailable')
    return e
end
function M.support()
    local ok,e=pcall(plugin)
    return {available=ok,source='eventful.onReport',fallback='native_report_cursor',
        reason=not ok and tostring(e):sub(1,240) or nil,
        attack_attribution='Native wound IDs; eventful attack callbacks are not complete in Adventure mode'}
end
function M.watch(after,limit)
    assert(type(after)=='number' and after%1==0 and after>=-1,'Invalid report cursor')
    assert(type(limit)=='number' and limit%1==0 and limit>=1 and limit<=4096,'Invalid report window limit')
    local stream={stats={source='native_report_cursor',events=0,catchup=0},cursor=after}
    local rows={}
    local stop
    local function append(r,kind)
        if not r or r.id<=stream.cursor or stream.reason then return end
        if #rows>=limit then stream.reason='Report event window exceeds '..limit;return end
        rows[#rows+1]={id=r.id,type=df.announcement_type[r.type],text=r.text}
        stream.cursor=r.id;stream.stats[kind]=stream.stats[kind]+1
    end
    function stream:window(cursor)
        if self.reason then return nil,self.reason end
        if self.closed then return nil,'Report event window is closed' end
        local reports=df.global.world.status.reports
        local total=#reports
        local latest=total>0 and reports[total-1].id or -1
        if latest<self.cursor then return nil,'Native report cursor reset' end
        if latest>self.cursor then
            local lo,hi=0,total
            while lo<hi do
                local mid=(lo+hi)//2
                if reports[mid].id>self.cursor then hi=mid else lo=mid+1 end
            end
            for i=lo,total-1 do
                append(reports[i],'catchup')
                if self.reason then return nil,self.reason end
            end
        end
        local out={}
        for i=#rows,1,-1 do
            if rows[i].id<=cursor then break end
            out[#out+1]=rows[i]
        end
        return out
    end
    function stream:close()
        if self.closed then return end
        self.closed=true;self.stats.closed=true
        if stop then stop()end
    end
    local ok,e=pcall(plugin)
    if ok then
        dfhack.df_llm_report_serial=(dfhack.df_llm_report_serial or 0)+1
        local key='df_llm_reports_'..dfhack.df_llm_report_serial
        stop=function()e.onReport[key]=nil;dfhack.onStateChange[key]=nil end
        local registered,err=pcall(function()
            -- Do not request frequency zero: eventful is shared, and lowering
            -- its frequency cannot be undone with enableEvent alone.
            e.enableEvent(e.eventType.REPORT,1)
            e.onReport[key]=function(id)
                if stream.closed or stream.reason or id<=stream.cursor then return end
                local read,why=pcall(function()
                    append(assert(df.report.find(id),'Reported native ID is no longer retained'),'events')
                end)
                if not read then stream.reason=tostring(why):sub(1,240)end
            end
            dfhack.onStateChange[key]=function(code)
                if code==SC_WORLD_UNLOADED or code==SC_MAP_UNLOADED then
                    stream.reason='World or map changed during report observation';stream:close()
                end
            end
        end)
        if registered then stream.stats.source='eventful.onReport'
        else stop();stream.stats.fallback_reason=tostring(err):sub(1,240)end
    else stream.stats.fallback_reason=tostring(e):sub(1,240)end
    return stream
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
