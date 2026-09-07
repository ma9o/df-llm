--@ module=true
--luacheck: globals factory
-- Development-only oracle for comparing a helper result to a visible warning.
-- Production status and receipts never load this screen-buffer scanner.
local function build()
local M={}
function M.burden(status)
    local source='native_hud_texture'
    local function unknown(reason)return {available=false,source=source,reason=reason}end
    if status.mode~='adventure' or not status.map_loaded or not status.can_move
        or status.modal or #(status.open_panels or {})>0 then
        return unknown('The adventure HUD is not exposed in the current interface')
    end
    local ok,result=pcall(function()
        local w,h=dfhack.screen.getWindowSize()
        assert(w>0 and h>0 and w*h<=120000,'HUD buffer dimensions are unavailable or bounded')
        local native=df.global.gps.graphical_interface
        local kinds={Burdened=native.texpos_adventure_burden_light,Overburdened=native.texpos_adventure_burden_heavy}
        local ids={}
        for label,tiles in pairs(kinds)do for _,id in ipairs(tiles)do
            assert(type(id)=='number' and id>0,'Native burden textures are unavailable')
            assert(not ids[id] or ids[id]==label,'Native burden texture identities overlap')
            ids[id]=label
        end end
        local hints=dfhack.df_llm_hud_hint
        local function sample(cells)
            local found,labels={},{}
            for _,p in ipairs(cells)do
                local pen=dfhack.screen.readTile(p.x,p.y)
                local label=pen and ids[pen.tile]
                if label then found[#found+1]=p;labels[label]=true end
            end
            if labels.Burdened and labels.Overburdened then
                return nil,'Conflicting burden icons are present'
            end
            local label=next(labels)
            if label then
                dfhack.df_llm_hud_hint={width=w,height=h,epoch=status.world_epoch,cells=found}
                return {available=true,label=label,state=label=='Burdened' and 'burdened' or 'overburdened',
                    burdened=true,overburdened=label=='Overburdened',source=source}
            end
        end
        -- Hints only accelerate a positive match. A moved/replaced icon causes a
        -- fresh scan; cached absence is never evidence of being unburdened.
        if hints and hints.width==w and hints.height==h and hints.epoch==status.world_epoch then
            local value,reason=sample(hints.cells)
            if value then return value end
            if reason then return unknown(reason)end
        end
        -- Search from the HUD edge, without assuming any fixed row or column.
        for y=h-1,0,-1 do
            local cells={};for x=0,w-1 do cells[#cells+1]={x=x,y=y}end
            local value,reason=sample(cells)
            if value then return value end
            if reason then return unknown(reason)end
        end
        return unknown('No burden icon was found; absence alone does not verify an unburdened HUD')
    end)
    return ok and result or unknown(tostring(result):sub(1,200))
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
