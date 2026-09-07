--@ module=true
--luacheck: globals factory
local function build(...)
-- Native save UI and file evidence. No simulation writes or rendered labels.
local h=...
local M={}
local reserved={current=true,['autosave 1']=true,['autosave 2']=true,['autosave 3']=true}
function M.validate_name(name)
    assert(type(name)=='string' and #name>=1 and #name<=40
        and name:match('^[A-Za-z0-9][A-Za-z0-9 _%-]*$') and not reserved[name:lower()],
        'Save name must be 1..40 letters, digits, spaces, underscores or hyphens; native working/autosave folders are reserved')
    return name
end
function M.supported()
    return h.bindings.support().native_hotkey_available
        and df.interface_key.SELECT~=nil and df.interface_key.STRING_A000~=nil
end
function M.menu(ui)
    local a=df.global.game.main_interface.options
    if not a.open then return nil end
    local out={kind='options',open=true,options=h.array()}
    local ok,err=pcall(function()
        out.context=df.options_context_type[a.context]
        assert(out.context=='MAIN_ADVENTURE','Save adapter requires native MAIN_ADVENTURE options')
        for _,flag in ipairs({'fort_retirement_confirm','adv_retirement_confirm','fort_abandon_confirm',
            'adv_abandon_confirm','fort_quit_without_saving_confirm','adv_quit_without_saving_confirm',
            'entering_timeline','doing_help'}) do
            assert(type(a[flag])=='boolean' and not a[flag],'Unsupported native options state: '..flag)
        end
        assert(M.supported(),'No verified native save bindings for this build')
        local cx,cy=math.floor((ui.width-1)/2),math.floor(ui.height/2)
        local function choice(name,label,x,y,key)
            local entry={id='options:'..out.context..':'..out.mode..':'..name,
                kind='option',native_type=name,label=label,index=#out.options}
            if key then h.bindings.fixed(entry,key,true)
            elseif x>=0 and x<ui.width and y>=0 and y<ui.height then
                entry.visible=true;entry.click={x=x,y=y};entry.binding_source='native_layout'
            else entry.selection_unavailable='Native button is outside the current window' end
            out.options[#out.options+1]=entry
        end
        assert(type(a.do_manual_save)=='boolean' and type(a.manual_save_timer)=='number',
            'Native save progress is unavailable')
        if a.do_manual_save or a.manual_save_timer>0 then out.mode='saving';return end
        assert(type(a.entering_manual_folder)=='boolean' and type(a.confirm_manual_overwrite)=='boolean',
            'Native filename mode is unavailable')
        if a.confirm_manual_overwrite then
            out.mode='overwrite';out.filename=h.text(a.entering_manual_str)
            choice('OVERWRITE','Overwrite this save',cx-25,cy+3)
            choice('CANCEL','Cancel overwrite',cx+24,cy+3)
        elseif a.entering_manual_folder then
            out.mode='filename';out.filename=h.text(a.entering_manual_str)
            choice('SUBMIT_FILENAME','Save',nil,nil,'SELECT')
            choice('CANCEL','Cancel filename entry',cx+24,cy+2)
        else
            out.mode='main'
            local count,lines=#a.option,#a.text.text
            assert(count<=32 and lines<=100,'Native options layout exceeds the supported bounds')
            -- Native feed 0x1e3910 has mouse rectangles, no OPTION hotkeys.
            -- Rows depend on native option/text counts. Its horizontally
            -- centered frame changes this interior x by at most one cell.
            local first=cy-math.floor(((lines>0 and lines+7 or 6)+3*count)/2)+4
                +(lines>0 and lines+1 or 0)
            for i=0,count-1 do
                local name=assert(df.main_menu_option_type[a.option[i]],'Unknown native main-menu option')
                choice(name,name:gsub('_',' '),cx,first+3*i+1)
            end
        end
    end)
    if not ok then out.selection_unavailable=tostring(err):sub(1,240) end
    return h.bindings.catalog(out)
end
function M.file(name)
    M.validate_name(name)
    local out={name=name,available=true}
    local ok,err=pcall(function()
        -- getSavePath() still points at the install directory in this build.
        -- DF's current data root follows its portable/per-user configuration.
        local root=dfhack.filesystem.getBaseDir()..'/save/'
        assert(dfhack.filesystem.isdir(root),'Native save data root is unavailable')
        out.directory_exists=dfhack.filesystem.isdir(root..name)
        out.world_exists=dfhack.filesystem.isfile(root..name..'/world.sav')
        if out.world_exists then
            local modified=dfhack.filesystem.mtime(root..name..'/world.sav')
            assert(type(modified)=='number' and modified>=0,'Saved world timestamp is unavailable')
            out.world_mtime=tostring(modified) -- opaque native timestamp; keep integer precision
        end
    end)
    if not ok then out.available=false;out.reason=tostring(err):sub(1,240) end
    return out
end
function M.edit(name,ui)
    M.validate_name(name)
    local menu=M.menu(ui)
    assert(menu and menu.mode=='filename' and not menu.selection_unavailable,
        'No verified native save-name field is active')
    local a=df.global.game.main_interface.options
    local count=#a.entering_manual_str
    assert(count<=40,'Existing native filename exceeds its verified input limit')
    -- Native text handler 0xc39700: STRING_A000 removes exactly one byte.
    -- Verify each deletion and the final value; no direct UI or game-state write.
    for i=1,count do
        h.input('STRING_A000')
        assert(#a.entering_manual_str==count-i,'Native filename deletion did not take effect')
    end
    for i=1,#name do h.input(('STRING_A%03d'):format(name:byte(i))) end
    assert(a.entering_manual_str==name,'Native filename does not match the requested value')
    return count+#name
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
