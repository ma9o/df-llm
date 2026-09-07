--@ module=true
--luacheck: globals factory
local function build()
-- Harness-only state lifetime. No native pointers survive a request or reload.
local M={}
function M.open()
    local s=dfhack.df_llm_session or {serial=0,receipts={},order={}}
    dfhack.df_llm_session=s
    s.dispatches=s.dispatches or {};s.dispatch_order=s.dispatch_order or {}
    s.interrupt_requests=s.interrupt_requests or {};s.interrupt_order=s.interrupt_order or {}
    if not s.boot_id then
        s.boot_id=dfhack.internal.md5(tostring({})..':'..os.time()..':'..dfhack.getTickCount()):sub(1,12)
        s.world_generation=0
    end
    s.map_generation=s.map_generation or 0
    s.world_epoch=s.boot_id..'.'..s.world_generation
    dfhack.onStateChange.df_llm_session=function(code)
        if code==SC_MAP_LOADED or code==SC_MAP_UNLOADED then
            dfhack.df_llm_session.map_generation=dfhack.df_llm_session.map_generation+1
            return
        end
        if code~=SC_WORLD_LOADED and code~=SC_WORLD_UNLOADED then return end
        local current=dfhack.df_llm_session
        current.world_generation=current.world_generation+1
        current.world_epoch=current.boot_id..'.'..current.world_generation
        local active=current.active_dispatch and current.dispatches[current.active_dispatch]
        if active then active.interrupted=true;active.world_changed=true end
        current.active_dispatch=nil;current.pending=nil
        current.interrupt_requests={};current.interrupt_order={}
        -- Retain plain diagnostic records and monotonic choice serials. Changed
        -- scope prevents old handles from naming another world's option set.
        local choices=dfhack.df_llm_choices
        if choices then choices.entries={};choices.order={} end
    end
    return s
end
function M.matches(record,session)
    return record.world_epoch~=nil and record.world_epoch==session.world_epoch
end
function M.resume_reason(record,session,status)
    if not M.matches(record,session) then return 'World changed; old dispatch progress cannot be resumed' end
    if record.adventurer_id~=status.adventurer_id then return 'Cannot resume as a different adventurer' end
    -- A native manual save changes the folder name while this world and actor
    -- remain loaded. World epochs, not mutable save labels, guard their lifetime.
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
