--@ module=true
--luacheck: globals factory
local function build(h)
-- Adventure extension to DFHack quicksave's native save-request approach.
-- Provenance: options_interfacest.entering_manual_folder/entering_manual_str,
-- SELECT's native filename handler, and do_manual_save's pending request.
-- Overwrite preparation follows DFHack scripts/quicksave.lua: the same saverst
-- request and offload worklists, with the named save_substage.Initializing tag.
-- The five-frame save startup delay is upstream's request initialization, not
-- a simulation clock. No game data, outcomes, or serialization are implemented.
local M={}
local reserved={current=true,['autosave 1']=true,['autosave 2']=true,['autosave 3']=true}
function M.validate_name(name)
    assert(type(name)=='string' and #name>=1 and #name<=40
        and name:match('^[A-Za-z0-9][A-Za-z0-9 _%-]*$') and not reserved[name:lower()],
        'Save name must be 1..40 letters/digits/spaces/underscores/hyphens; native working/autosave folders are reserved')
    return name
end
function M.file(name)
    M.validate_name(name)
    local out={name=name,available=true}
    local ok,err=pcall(function()
        local root=dfhack.filesystem.getBaseDir()..'/save/'
        assert(dfhack.filesystem.isdir(root),'Native save data root is unavailable')
        out.directory_exists=dfhack.filesystem.isdir(root..name)
        out.world_exists=dfhack.filesystem.isfile(root..name..'/world.sav')
        if out.world_exists then
            local modified=dfhack.filesystem.mtime(root..name..'/world.sav')
            assert(type(modified)=='number' and modified>=0,'Saved world timestamp is unavailable')
            out.world_mtime=tostring(modified)
        end
    end)
    if not ok then out.available=false;out.reason=tostring(err):sub(1,240)end
    return out
end
function M.validate(action)
    M.validate_name(action.name)
    assert(action.overwrite==nil or type(action.overwrite)=='boolean','overwrite must be boolean')
    local file=M.file(action.name)
    assert(file.available,file.reason)
    assert(not file.directory_exists or action.overwrite,'The save already exists; overwrite was not delegated')
    assert(dfhack.isMapLoaded() and dfhack.world.isAdventureMode(),'Quicksave requires a loaded adventure')
    local s=dfhack.gui.getCurViewscreen(true)
    assert(df.viewscreen_dungeonmodest:is_instance(s),'Quicksave requires the native adventure screen')
    assert(df.global.adventure.menu==df.ui_advmode_menu.Default
        and df.global.adventure.player_control_state==df.adventure_game_loop_type.TAKING_INPUT,
        'Quicksave requires the local adventure input boundary')
    local focus=dfhack.gui.getCurFocus(true)
    assert(#focus==1 and focus[1]=='dungeonmode/Default','Finish the active interface before quicksave')
    assert(not df.global.game.main_interface.options.open,'Finish the active options operation before quicksave')
end
function M.submit(action)
    M.validate(action) -- No UI write or input precedes validation.
    h.input('OPTIONS') -- The game initializes and owns the shared options state.
    local a=df.global.game.main_interface.options
    assert(a.open and a.context==df.options_context_type.MAIN_ADVENTURE,
        'Native adventure options did not open')
    for _,key in ipairs({'do_manual_save','entering_manual_folder','confirm_manual_overwrite',
        'entering_timeline','doing_help','adv_retirement_confirm','adv_abandon_confirm',
        'adv_quit_without_saving_confirm'})do
        assert(a[key]==false,'Unexpected active native save state: '..key)
    end
    -- Fill the pending native filename choice, then run DF's own validation.
    a.entering_manual_str=action.name
    a.entering_manual_folder=true
    h.input('SELECT')
    if a.confirm_manual_overwrite then
        assert(action.overwrite,'Native overwrite requires explicit delegation')
        -- The controller supplied this native confirmation. Reuse quicksave's
        -- initialization of the pending save request; DF performs the save.
        -- Merely setting do_manual_save would reuse a finished saverst.
        local save=a.saver
        save.substage=df.save_substage.Initializing
        save.stage=0
        save.info.nemesis_save_file_id:resize(0)
        save.info.nemesis_member_idx:resize(0)
        save.info.units:resize(0)
        save.info.cur_unit_chunk=nil
        save.info.cur_unit_chunk_num=-1
        save.info.units_offloaded=-1
        a.manual_save_timer=5
        a.do_manual_save=true
    end
    assert(a.do_manual_save,'Native filename submission did not request a save')
    return {adapter='dfhack_quicksave',submitted=true,native_key_inputs=2}
end
function M.menu()
    local a=df.global.game.main_interface.options
    if not a.open then return end
    local out={kind='options',open=true,options=h.array(),context=df.options_context_type[a.context]}
    if a.do_manual_save or a.manual_save_timer>0 then out.mode='saving';return out end
    if a.confirm_manual_overwrite then out.mode='overwrite'
    elseif a.entering_manual_folder then out.mode='filename'
    else out.mode='main'end
    if out.mode~='main' then out.filename=h.text(a.entering_manual_str)end
    out.selection_unavailable='Use quicksave for a named checkpoint; other options require explicit development input'
    return out
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build
elseif type((...))=='table' then return build(...)
else
    local name,flag=...
    assert(flag==nil or flag=='--overwrite','Usage: quicksave NAME [--overwrite]')
    local m=build({array=function()return require('json.internal'):newArray{}end,text=dfhack.df2utf,
        input=function(key)require('gui').simulateInput(dfhack.gui.getCurViewscreen(true),key)end})
    m.submit({name=name,overwrite=flag=='--overwrite'})
    print('Native quicksave requested: '..name)
end
