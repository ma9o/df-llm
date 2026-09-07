--@ module=true
--luacheck: globals factory
local function build(...)
-- Build-scoped menu execution adapters. Reads never change interface state.
-- Scroll writes are part of explicit selection dispatches. An empty input pass
-- probes native bounds before the same request resolves its OPTION key. A
-- single-page list can leave an invalid stored offset untouched; it is not the
-- effective page start. Rendering alone does not normalize these fields.
local h=...
local M={}
function M.catalog(menu)
    -- Harness memory only. Tokens name a complete native option set, never an
    -- unchecked row index. Scrolling preserves tokens; changed targets/order
    -- create new ones. Old tokens cannot bind to a different menu.
    if not menu or not menu.options or #menu.options==0 then return menu end
    dfhack.df_llm_choices=dfhack.df_llm_choices or {serial=0,entries={},order={}}
    local cache=dfhack.df_llm_choices
    local scope=dfhack.df_llm_session and dfhack.df_llm_session.world_epoch
    local ids={scope or '',menu.kind or '',tostring(menu.context),tostring(menu.activity_id),
        tostring(menu.target_unit_id),tostring(menu.mode),tostring(menu.selecting),
        tostring(menu.selecting_tact),tostring(menu.tact_topic_index)}
    for _,o in ipairs(menu.options) do ids[#ids+1]=o.id end
    local signature=table.concat(ids,'\n')
    local token=cache.entries[signature]
    if not token then
        cache.serial=cache.serial+1;token='c'..(scope and scope..'.' or '')..cache.serial
        cache.entries[signature]=token;cache.order[#cache.order+1]=signature
        if #cache.order>128 then cache.entries[table.remove(cache.order,1)]=nil end
    end
    for i,o in ipairs(menu.options) do o.handle=token..':'..(i-1) end
    return menu
end
local function supported()
    return dfhack.getDFVersion()=='v0.53.16 win64 STEAM'
end
local inventory_contexts={'MAIN','DROP','WEAR','REMOVE','PUT_IN','EAT_DRINK','INTERACT',
    'PUT_IN_DESTINATION','INTERACT_LIST','ONE_ITEM_FULL_LIST','THROW'}
function M.inventory_supported(context)
    local enum=df.adventure_interface_inventory_context_type
    if not enum or type(context)~='number' then return false end
    for _,name in ipairs(inventory_contexts) do if enum[name]==context then return true end end
    return false
end
function M.support()
    local keys=true
    for i=1,20 do if df.interface_key['OPTION'..i]==nil then keys=false end end
    local available=supported() and keys
    return {method=available and 'native_hotkey' or 'ascii_ordered_labels',
        native_hotkey_available=available,verified_build=supported(),keys_available=keys,
        inventory_contexts=inventory_contexts,
        scroll_bounds='Probed through native empty feed; a stored offset is not assumed to be the effective page start'}
end
function M.bind(entry,index,_,verified)
    if not verified or not M.support().native_hotkey_available then return entry end
    entry.selection={method='native_hotkey',scroll_to=index}
    return entry
end
function M.fixed(entry,key,verified)
    if verified and M.support().native_hotkey_available and df.interface_key[key]~=nil then
        entry.selection={method='native_key',key=key}
    end
    return entry
end
function M.combat_supported(menu)
    return menu.kind=='combat' and (menu.mode=='UNIT_CHOICE' or menu.mode=='MOVE_CHOICE'
        or menu.mode=='AIM_TARGET' or menu.mode=='AIM_ATTACK')
        and M.support().native_hotkey_available
end
function M.combat_list(menu)
    local panel=df.global.game.main_interface.adventure.attack
    assert(panel.open and df.adventure_interface_attack_mode_type[panel.mode]==menu.mode,
        'Combat mode changed before reading its active list')
    local list,field,drag,count
    if menu.mode=='UNIT_CHOICE' then
        list=panel.unit_choice;field='scroll_position_unit_choice';drag=panel.scrolling_unit_choice
    elseif menu.mode=='MOVE_CHOICE' then
        list=panel.move_choice;field='scroll_position_move_choice';drag=panel.scrolling_move_choice
    elseif menu.mode=='AIM_TARGET' then
        local info=df.global.world.attack_chance_info
        list=info.target;count=info.current_target_number
        -- This vector is a reusable allocation. Entries after the native count
        -- are not current choices and must never be dereferenced.
        assert(type(count)=='number' and count==math.floor(count) and count>=0 and count<=#list,
            'Native aim-target count is invalid')
        field='scroll_position_aim_target';drag=panel.scrolling_aim_target
    elseif menu.mode=='AIM_ATTACK' then
        list=panel.custom_combat.aim_mod;field='scroll_position_aim_attack';drag=panel.scrolling_aim_attack
    else error('No verified native combat list for this mode',0) end
    return list,field,drag,count or #list
end
function M.conversation_supported(menu)
    return menu.kind=='conversation' and not menu.entering_filter
        and M.support().native_hotkey_available
end
function M.bind_topic(entry,menu,line_start,key_index)
    if M.conversation_supported(menu) then
        entry.selection={method='native_hotkey',indexing='conversation_lines',
            scroll_to=line_start,key_index=key_index}
    end
    return entry
end
function M.list_supported(menu)
    return (menu.kind=='movement' or menu.kind=='option_list') and M.support().native_hotkey_available
end
function M.key(index,scroll)
    local offset=index-scroll
    assert(offset>=0 and offset<20,'Normalized native option is outside the supported hotkey range')
    local key='OPTION'..(offset+1)
    assert(df.interface_key[key]~=nil,'Native option hotkey is unavailable')
    return key
end
function M.selection_key(menu,option)
    local selection=option.selection
    if selection.method=='native_key' then
        assert(M.support().native_hotkey_available and df.interface_key[selection.key]~=nil,
            'Native choice key is unavailable')
        return selection.key
    end
    if selection.indexing=='conversation_lines' then
        assert(M.conversation_supported(menu) and type(selection.key_index)=='number',
            'Conversation choice has no normalized native hotkey')
        return M.key(selection.key_index,0)
    end
    return M.key(option.index,menu.scroll)
end
function M.text_binding(entry,_,_,ui)
    -- Isolated compatibility adapter for menu families/builds not yet verified.
    if not entry.label then return entry end
    local function normalized(s)return s:gsub('%s+',' '):match('^%s*(.-)%s*$')end
    local candidates={}
    for _,row in ipairs(ui.rows) do
        local key,label=row.text:match('^%s*([a-z]) (.-)%s*$')
        label=label and normalized(label)
        local full=normalized(entry.label)
        local prefix=label and label:gsub('%.%.%.$',''):gsub('…$','')
        if key and (label==full or (#prefix>=8 and full:sub(1,#prefix)==prefix)) then
            local first=row.text:find(key..' ',1,true)
            candidates[#candidates+1]={x=utf8.len(row.text:sub(1,first-1))+2,y=row.y}
        end
    end
    if #candidates==1 then entry.visible=true;entry.click=candidates[1] end
    return entry
end
function M.binding(entry,index,scroll,ui,verified)
    M.bind(entry,index,scroll,verified)
    if not entry.selection then M.text_binding(entry,index,scroll,ui) end
    return entry
end
function M.text_menu(menu,ui)
    if menu.selection_unavailable then return menu end
    local function normalized(s)return s:gsub('%s+',' '):match('^%s*(.-)%s*$')end
    local function matches(option,label)
        if not option.label or option.selection then return false end
        local full=normalized(option.label)
        local prefix=label:gsub('%.%.%.$',''):gsub('…$','')
        return label==full or (#prefix>=8 and full:sub(1,#prefix)==prefix)
    end
    local rows={}
    local options=menu.options or {}
    local native=#options>0
    for _,o in ipairs(options)do if not o.selection then native=false;break end end
    if native then return menu end
    for _,option in ipairs(options) do
        if not option.selection then option.visible=nil;option.click=nil;option.selection_unavailable=nil end
    end
    for _,row in ipairs(ui.rows) do
        local key,label=row.text:match('^%s*([a-z]) (.-)%s*$')
        if key then
            label=normalized(label)
            local candidates={}
            for i,option in ipairs(options) do
                if matches(option,label) then candidates[#candidates+1]=i end
            end
            if #candidates>0 then
                local first=row.text:find(key..' ',1,true)
                rows[#rows+1]={label=label,candidates=candidates,key=key,
                    click={x=utf8.len(row.text:sub(1,first-1))+2,y=row.y}}
            end
        end
    end
    -- A page of truncated names can still have a unique correspondence to the
    -- native ordered list. Require one contiguous alignment, one column and
    -- consecutive displayed shortcuts. Never resolve a lone ambiguous prefix
    -- by guessing which hidden native entry is at the top of the page.
    local starts={}
    for start=1,#options-#rows+1 do
        local valid=#rows>0
        for j,row in ipairs(rows) do
            if not matches(options[start+j-1],row.label) or
                (j>1 and (row.click.x~=rows[j-1].click.x or row.key:byte()~=rows[j-1].key:byte()+1)) then
                valid=false;break
            end
        end
        if valid then starts[#starts+1]=start end
    end
    if #starts==1 then
        for j,row in ipairs(rows) do
            local option=options[starts[1]+j-1]
            option.visible=true;option.click=row.click
        end
    else
        -- Exact isolated labels may remain usable when a complete page cannot
        -- be aligned. Both the native entry and rendered row must be unique.
        local candidates={}
        for _,row in ipairs(rows) do for _,i in ipairs(row.candidates) do
            candidates[i]=(candidates[i] or 0)+1
        end end
        for _,row in ipairs(rows) do
            local i=row.candidates[1]
            if #row.candidates==1 and candidates[i]==1 then
                options[i].visible=true;options[i].click=row.click
            end
        end
    end
    for _,row in ipairs(rows) do for _,i in ipairs(row.candidates) do
        if not options[i].visible then
            options[i].selection_unavailable='Rendered option labels are ambiguous on this page'
        end
    end end
    return menu
end
function M.scroll(menu,option)
    assert(M.support().native_hotkey_available and option.selection and option.selection.method=='native_hotkey',
        'No verified native scroll adapter for this menu/build')
    assert(type(option.index)=='number' and option.index>=0 and option.index<500,
        'Invalid native option index')
    local a=df.global.game.main_interface.adventure
    local panel,field,list,extent
    local requested=option.selection.scroll_to or option.index
    if menu.kind=='inventory' and a.inventory.open then
        panel=a.inventory;field='scroll_position'
        assert(M.inventory_supported(panel.context),'No verified native scroll adapter for this inventory context')
        assert(not panel.scrolling,'Finish dragging the inventory scroll bar before selection')
        list=panel.option_current
    elseif menu.kind=='option_list' and a.option_list.open then
        panel=a.option_list;field='scroll_position';list=panel.option
        assert(not panel.scrolling and not panel.doing_pickup_amount and not panel.entering_number,
            'Finish the ground list scroll/quantity choice before selection')
    elseif menu.kind=='movement' and a.movement_options.open then
        panel=a.movement_options;field='scroll_gait'
        assert(not panel.scrolling_gait,'Finish dragging the gait scroll bar before selection')
        list=panel.speed_sneak_un.body.body_plan.gait_info[panel.gait_type]
    elseif menu.kind=='combat' and a.attack.open then
        panel=a.attack
        assert(M.combat_supported(menu) and df.adventure_interface_attack_mode_type[panel.mode]==menu.mode,
            'No verified native scroll adapter for this combat mode')
        local dragging
        list,field,dragging,extent=M.combat_list(menu)
        assert(not dragging,'Finish dragging the combat list before selection')
    elseif menu.kind=='conversation' and a.conversation.open then
        panel=a.conversation
        assert(not panel.entering_conv_string_filter,'Cannot scroll while entering a conversation filter')
        local scrolling
        if panel.selecting_conversation then
            field='select_scroll_position';scrolling=panel.select_scrolling;list=panel.select_option
        elseif panel.selecting_tact then
            field='tact_scroll_position';scrolling=panel.tact_scrolling;list=panel.tact_list
        else
            field='choice_scroll_position';scrolling=panel.choice_scrolling;list=panel.conv_choice_info
        end
        assert(not scrolling,'Finish dragging the conversation scroll bar before selection')
        if not panel.selecting_conversation and not panel.selecting_tact then
            assert(option.selection.indexing=='conversation_lines','Conversation topics require line-based indexing')
            extent=0;for _,info in ipairs(list)do extent=extent+#info.title.text+2 end
        end
    else error('No verified native scroll adapter for this menu',0) end
    assert(option.index<#list,'Option disappeared before scroll')
    extent=extent or #list
    assert(option.index<extent,'Option is outside the current native choice count')
    -- The native feed clamps scrolling lists, but can leave the field untouched
    -- when everything fits. Probe an out-of-range offset: unchanged extent means
    -- no scrolling; otherwise DF returns its maximum. Set the requested position
    -- within those observed bounds. No page geometry or ASCII text is required.
    local before=panel[field]
    local ok,value=pcall(function()
        panel[field]=extent;h.normalize_ui()
        local observed=panel[field]
        assert(type(observed)=='number' and observed==math.floor(observed) and observed>=0 and observed<=extent,
            'Native scroll bounds could not be verified')
        local maximum=observed==extent and 0 or observed
        panel[field]=math.min(requested,maximum)
        return {kind=menu.kind,field=field,before=before,requested=requested,
            probe=extent,probe_result=observed,maximum=maximum,effective=panel[field]}
    end)
    if not ok then panel[field]=before;error(value,0) end
    return value
end
function M.prepare(menu,option)
    if option.selection.method=='native_key' then
        M.selection_key(menu,option)
        return nil
    end
    return M.scroll(menu,option)
end
function M.named(option)
    local s=df.new('string');local ok=pcall(function()option:getName(s)end)
    local name=ok and h.text(s.value) or nil;s:delete();return name
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
