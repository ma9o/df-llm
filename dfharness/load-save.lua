--@ module=true
--luacheck: globals start status
-- Repair of DFHack load-save for the native title-screen save catalog.
-- Provenance: df-structures viewscreen_titlest title_mode_type and save headers;
-- DFHack ci/test.lua click_top_title_button documents the native button layout.
-- Development/save management only. No game data, load stages, or caches are
-- constructed or changed: the native title handler creates the native loader.
local gui=require('gui')
local current
local function title()
    local s=dfhack.gui.getCurViewscreen(true)
    assert(df.viewscreen_titlest:is_instance(s) and not dfhack.isWorldLoaded(),
        'load-save requires the native title screen with no loaded world')
    assert(not s.managing_mods and not s.uploading_mods and not s.deleting_region
        and not s.deleting_savegame_game and not s.deleting_savegame_world and s.game_start_proceed==0,
        'Finish the active title-screen operation before loading')
    return s
end
local function find_header(list,name)
    assert(#list<=4096,'Native save catalog exceeds the reading limit')
    local found
    for i,h in ipairs(list)do if h.filename_noext==name then
        assert(not found,'Native save name is ambiguous');found={index=i,header=h}
    end end
    return found
end
local function click(s,index)
    local w,h=dfhack.screen.getWindowSize()
    local x,y=w//2,(h<60 and 25 or h//2+3)+3*index
    assert(index>=0 and x<w and y>=0 and y<h-3,'Native load button is outside the window')
    local g,e=df.global.gps,df.global.enabler
    local old={g.mouse_x,g.mouse_y,g.precise_mouse_x,g.precise_mouse_y,e.tracking_on}
    local ok,err=pcall(function()
        g.mouse_x=x;g.mouse_y=y
        g.precise_mouse_x=math.floor((x+0.5)*g.tile_pixel_x)
        g.precise_mouse_y=math.floor((y+0.5)*g.tile_pixel_y)
        gui.simulateInput(s,'_MOUSE_L')
    end)
    g.mouse_x=old[1];g.mouse_y=old[2];g.precise_mouse_x=old[3];g.precise_mouse_y=old[4];e.tracking_on=old[5]
    assert(ok,err)
end
local function advance()
    local ok,err=pcall(function()
        local s=dfhack.gui.getCurViewscreen(true)
        if df.viewscreen_loadgamest:is_instance(s) or dfhack.isWorldLoaded() then
            current.phase='loading';return
        end
        s=title()
        if current.pending_mode then
            assert(s.mode~=current.pending_mode,'Native title selection had no effect; input was not repeated')
            current.pending_mode=nil
        end
        local target=assert(find_header(s.savegame_header,current.name),'Save is absent from the native catalog')
        local index,scroll_field
        if s.mode==df.title_mode_type.MAIN_MENU then
            assert(#s.menu_line_id<=32,'Native title menu exceeds the reading limit')
            for i,v in ipairs(s.menu_line_id)do if v==df.main_choice_type.Continue then
                assert(index==nil,'Continue active game is ambiguous');index=i
            end end
        elseif s.mode==df.title_mode_type.CONTINUE_ACTIVE_WORLD then
            assert(#s.savegame_header_world<=4096,'Native world catalog exceeds the reading limit')
            local world=target.header.world_header
            for i,h in ipairs(s.savegame_header_world)do
                if h.world_header.id1==world.id1 and h.world_header.id2==world.id2 then
                    assert(index==nil,'Native world choice is ambiguous');index=i
                end
            end
            scroll_field='scroll_position_world_choice'
        elseif s.mode==df.title_mode_type.CONTINUE_ACTIVE then
            index=assert(find_header(s.savegame_header_game,current.name),'Requested save is not in this world').index
            scroll_field='scroll_position_game_choice'
        else error('The active title interface is not a supported load state')end
        assert(index~=nil,'Continue active game is unavailable')
        if scroll_field and current.scrolled_mode~=s.mode then
            -- Native render/input owns the effective scroll bound. Normalize on
            -- the next frame before resolving the requested row from fresh state.
            s[scroll_field]=index
            gui.simulateInput(s,{})
            current.scrolled_mode=s.mode
            dfhack.timeout(1,'frames',advance);return
        end
        if scroll_field then index=index-s[scroll_field]end
        current.pending_mode=s.mode
        current.inputs=current.inputs+1
        click(s,index)
        dfhack.timeout(1,'frames',advance)
    end)
    if not ok then current.phase='failed';current.reason=tostring(err)end
end
function start(name)
    assert(type(name)=='string' and #name>=1 and #name<=100 and not name:find('[/\\%z]')
        and name~='.' and name~='..' and name:lower()~='current','Invalid save folder name')
    local s=title()
    local found=assert(find_header(s.savegame_header,name),'Save is absent from the native catalog')
    assert(dfhack.filesystem.isfile(tostring(found.header.full_path)..'/world.sav'),'Native save has no world.sav')
    assert(not current or current.phase=='failed' or current.phase=='loading','Another load request is active')
    current={name=name,phase='selecting',inputs=0}
    advance()
    return status()
end
function status()
    if not current then return {phase='idle'}end
    local phase=current.phase
    if phase=='loading' and dfhack.isMapLoaded() then
        phase=df.global.world.cur_savegame.save_dir==current.name and 'completed' or 'interrupted'
    end
    return {name=current.name,phase=phase,inputs=current.inputs,reason=current.reason}
end
if not (dfhack_flags and dfhack_flags.module) then
    start((...))
    if current.phase=='failed' then qerror(current.reason)end
    print('Native load requested: '..current.name)
end
