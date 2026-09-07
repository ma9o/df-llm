--@ module=true
--luacheck: globals factory
local function build()
-- Delegate presentation acceleration to the installed DFHack overlay. This
-- does not advance simulation timers or acknowledge announcements. Read tools
-- never call arm(); only explicitly completed dispatches may request it.
local M={}
local function widget()
    local overlay=require('plugins.overlay')
    assert(overlay.isOverlayEnabled('advtools.fastcombat'),'advtools.fastcombat is disabled')
    local entry=overlay.get_state().db['advtools.fastcombat']
    local w=entry and entry.widget
    assert(w and type(w.onInput)=='function','Installed fastcombat overlay is unavailable')
    return w
end
function M.support()
    local ok,w=pcall(widget)
    return {available=ok,source='advtools.fastcombat',reason=not ok and tostring(w):sub(1,240) or nil,
        policy='Complete dispatches skip presentation delays; announcements still use delegated acknowledgement'}
end
function M.arm(session,request,receipt)
    if request.fastcombat~=true or not request.parent_dispatch then return end
    local epoch=session.world_epoch
    local out=M.support();out.policy=nil;receipt.presentation=out
    if not out.available then return end
    out.activated=false
    local function activate()
        if session.world_epoch~=epoch or receipt.error then return end
        local parent=session.dispatches[request.parent_dispatch]
        if not parent or parent.interrupted or session.active_dispatch~=request.parent_dispatch then return end
        if not dfhack.isMapLoaded() or not dfhack.world.isAdventureMode() then return end
        if not df.viewscreen_dungeonmodest:is_instance(dfhack.gui.getCurViewscreen(true)) then return end
        local phase=df.global.adventure.player_control_state
        if phase==df.adventure_game_loop_type.TAKING_INPUT
            or phase==df.adventure_game_loop_type.TAKING_TOO_LONG_INPUT then return end
        local ok,err=pcall(function()widget():onInput({SELECT=true})end)
        out.activated=ok
        if not ok then out.reason=tostring(err):sub(1,240)end
    end
    activate()
    if not out.activated then
        -- The native handler may start processing on the next frame. This is
        -- a single deferred activation, scoped to the same submitted input.
        dfhack.timeout(1,'frames',function()if not receipt.settled then activate()end end)
    end
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
