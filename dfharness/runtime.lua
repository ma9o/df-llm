--@ module=true
--luacheck: globals factory
local function build(...)
-- Read-only dependency discovery. No cached native pointers or numeric key IDs.
local h=...
local M={}
local function value(fn)
    local ok,v=pcall(fn)
    if ok then return v end
end
local function resolve(path)
    local current={df=df,dfhack=dfhack}
    for name in path:gmatch('[^.]+') do current=current[name] end
    return current
end
function M.panels()
    local out={available=true,flags={},unclassified=h.array()}
    local ok,err=pcall(function()
        -- Two known interface structs only. Adventure also uses shared panels
        -- such as the name creator; absence of an adventure flag is not proof
        -- that the interface is decoded. Never follow arbitrary native pointers.
        local main=df.global.game.main_interface
        local function scan(root,prefix)
            for name,panel in pairs(root) do if name~='adventure' then
                local key=name=='help' and name or prefix..tostring(name)
                local open=value(function()return panel.open end)
                if type(open)=='boolean' then out.flags[key]=open
                else out.unclassified[#out.unclassified+1]=key end
            end end
        end
        scan(main.adventure,'');scan(main,'main.')
    end)
    if not ok then out.available=false;out.reason=tostring(err):sub(1,240) end
    table.sort(out.unclassified)
    return out
end
function M.saving()
    -- Only active shared options own these fields; flags persist after closing.
    local a=df.global.game.main_interface.options
    if not a.open then return false end
    assert(type(a.do_manual_save)=='boolean' and type(a.manual_save_timer)=='number',
        'Native manual-save state is unavailable')
    return a.do_manual_save or a.manual_save_timer>0
end
function M.army_activity(army)
    if not army then return {available=true,present=false} end
    local out={available=true,present=true,id=army.id}
    local ok,err=pcall(function()
        out.remaining=army.travel_count
        assert(type(out.remaining)=='number','Native party activity counter is unavailable')
        out.active=false;out.flags={}
        for _,name in ipairs({'sleeping','waiting','composing','working'}) do
            local tag=df.army_flags[name]
            assert(type(tag)=='number','Native party activity tag is unavailable: '..name)
            local flag=army.flags[tag]
            assert(type(flag)=='boolean','Native party activity flag is unavailable: '..name)
            out.flags[name]=flag
            out.active=out.active or flag
        end
    end)
    if not ok then out.available=false;out.active=nil;out.reason=tostring(err):sub(1,240) end
    return out
end
function M.announcement()
    local ok,result=pcall(function()
        local s=df.global.world.status
        -- Mega-announcements use a separate queue and may cover a default
        -- adventure screen while adv_showing_announcements is false. Only the
        -- first queued popup owns the displayed message (native feed 0xea4d0).
        assert(type(s.popups)=='table' or type(s.popups)=='userdata','Native popup queue is unavailable')
        local count=#s.popups
        if count>0 then
            local popup=s.popups[0]
            assert(type(popup.text)=='string','Native popup text is unavailable')
            return {available=true,open=true,native_kind='popup',count=count,
                text=h.text(popup.text),more=false}
        end
        local open=s.temp_flag.adv_showing_announcements
        assert(type(open)=='boolean','Native announcement flag is unavailable')
        if not open then return {available=true,open=false} end
        local more=s.temp_flag.adv_have_more
        assert(type(more)=='boolean' and type(s.adv_scroll_position)=='number',
            'Native announcement page state is unavailable')
        return {available=true,open=true,more=more,scroll=s.adv_scroll_position,
            lines=#s.adv_announcement}
    end)
    if ok then return result end
    return {available=false,reason=tostring(result):sub(1,240)}
end
function M.acknowledgement_key(modal)
    -- Native SELECT is handled by dungeonmode/advtools for the announcement
    -- panel even when the premium UI exposes no textual Okay button. Verified
    -- live on the supported build with no time or position advancement.
    if modal.kind=='announcement' and modal.source=='native'
        and h.bindings.support().native_hotkey_available then
        local key=modal.native_kind=='popup' and 'CLOSE_MEGA_ANNOUNCEMENT' or 'SELECT'
        if type(df.interface_key[key])=='number' then return key end
    end
end
local requirements={
    announcements={
        {path='df.global.world.status.popups',type='vector'},
        {path='df.global.world.status.temp_flag.adv_showing_announcements',type='boolean'},
        'df.interface_key.SELECT','df.interface_key.CLOSE_MEGA_ANNOUNCEMENT'},
    saving={'df.global.game.main_interface.options.open','df.global.game.main_interface.options.option',
        {path='df.global.game.main_interface.options.entering_manual_folder',type='boolean'},
        {path='df.global.game.main_interface.options.entering_manual_str',type='string'},
        {path='df.global.game.main_interface.options.confirm_manual_overwrite',type='boolean'},
        {path='df.global.game.main_interface.options.do_manual_save',type='boolean'},
        'df.global.game.main_interface.options.manual_save_timer',
        'df.interface_key.OPTIONS','df.interface_key.SELECT','df.interface_key.STRING_A000',
        'df.options_context_type.MAIN_ADVENTURE','df.main_menu_option_type.SAVE_AND_CONTINUE',
        'dfhack.filesystem.getBaseDir','dfhack.filesystem.isdir','dfhack.filesystem.isfile','dfhack.filesystem.mtime'},
    core={'dfhack.gui.getCurViewscreen','dfhack.world.getAdventurer','dfhack.isWorldLoaded',
        'dfhack.isMapLoaded','df.interface_key.LEAVESCREEN','df.adventure_game_loop_type.TAKING_INPUT',
        'df.adventure_game_loop_type.TAKING_TOO_LONG_INPUT','df.global.adventure.player_control_state'},
    local_map={'dfhack.maps.getTileBlock','dfhack.maps.getTileSize','dfhack.maps.isTileVisible',
        'dfhack.maps.getTileFlags','dfhack.maps.getTileType','dfhack.maps.getWalkableGroup',
        'dfhack.units.isVisible','dfhack.units.isHidden','df.interface_key.A_MOVE_N',
        'df.interface_key.A_MOVE_S','df.interface_key.A_MOVE_E','df.interface_key.A_MOVE_W'},
    native_path={'dfhack.units.setPathGoal','dfhack.maps.canWalkBetween','dfhack.maps.isTileVisible',
        {path='df.adventure_movement_pathst.new',type='function'},
        'df.unit_path_goal.AdventureAutomove','df.unit_path_goal.None',
        'df.dungeon_control_state.CONTINUE','df.dungeon_control_state.PROMPT','df.interface_key.A_SHORT_WAIT'},
    inventory={'dfhack.items.getContainedItems','df.global.game.main_interface.adventure.inventory.open',
        'df.global.game.main_interface.adventure.inventory.option_current',
        'df.global.game.main_interface.adventure.inventory.scroll_position','df.interface_key.A_INV_DROP',
        'df.interface_key.A_INV_WEAR','df.interface_key.A_INV_REMOVE','df.interface_key.A_INV_PUTIN'},
    burden={'dfhack.units.getPhysicalAttrValue','dfhack.units.getEffectiveSkill','dfhack.units.isHidingCurse',
        'df.physical_attribute_type.STRENGTH','df.job_skill.ARMOR',
        'df.inv_item_role_type.Worn','df.inv_item_role_type.WrappedAround'},
    ground_options={'df.global.game.main_interface.adventure.option_list.open',
        'df.global.game.main_interface.adventure.option_list.option','df.interface_key.A_GROUND'},
    consumption={'df.interface_key.A_INV_EATDRINK','df.adventure_option_type.EAT_DRINK_ITEM',
        'df.announcement_type.EAT_ITEM','df.announcement_type.DRINK_ITEM'},
    environmental_consumption={'df.interface_key.A_INV_EATDRINK',
        'df.adventure_environment_ingest_materialst.is_instance',
        'df.adventure_interface_inventory_context_type.EAT_DRINK','df.matter_state.Liquid',
        'df.announcement_type.DRINK_ITEM','df.announcement_type.CONSUME_FAILURE','dfhack.matinfo.decode'},
    emptying={'df.adventure_option_drop_itemst.is_instance','dfhack.items.getContainer',
        'df.interface_key.A_INV_DROP','df.announcement_type.EMPTY_CONTAINER'},
    conversation={'df.interface_key.A_TALK','df.global.game.main_interface.adventure.conversation.open',
        'df.global.game.main_interface.adventure.conversation.conv_choice_info',
        'df.global.game.main_interface.adventure.conversation.select_option',
        'df.activity_event_conversationst.is_instance','df.talk_choice_type.Greet','df.talk_choice_type.ReturnToMain'},
    conversation_tacts={
        {path='df.global.game.main_interface.adventure.conversation.selecting_tact',type='boolean'},
        {path='df.global.game.main_interface.adventure.conversation.tact_list',type='vector'},
        {path='df.global.game.main_interface.adventure.conversation.tact_scrolling',type='boolean'},
        'df.global.game.main_interface.adventure.conversation.tact_scroll_position',
        'df.conversation_tact_type.Persuade','df.conversation_tact_type.Intimidate',
        'df.talk_choice_type.FishForMaster','df.talk_choice_type.FishForPlots'},
    combat={'df.interface_key.A_ATTACK','df.interface_key.A_ATTACK_CONFIRM','df.global.game.main_interface.adventure.attack.open',
        'df.global.game.main_interface.adventure.attack.unit_choice',
        'df.global.game.main_interface.adventure.attack.move_choice',
        'df.global.game.main_interface.adventure.attack.scroll_position_unit_choice',
        'df.global.game.main_interface.adventure.attack.scroll_position_move_choice',
        'df.global.game.main_interface.adventure.attack.custom_combat.aim_mod',
        'df.global.game.main_interface.adventure.attack.scroll_position_aim_target',
        'df.global.game.main_interface.adventure.attack.scroll_position_aim_attack',
        'df.global.world.attack_chance_info.current_target_number',
        'df.adventure_interface_attack_mode_type.AIM_TARGET','df.adventure_interface_attack_mode_type.AIM_ATTACK',
        'df.adventure_interface_attack_mode_type.MOVE_CHOICE'},
    travel={'df.interface_key.A_TRAVEL','df.interface_key.A_END_TRAVEL','df.global.adventure.travel_origin_x',
        'df.global.adventure.travel_origin_y','df.global.adventure.travel_not_moved',
        'df.global.adventure.offload_timer','df.adventure_travel_exception_type.NONE'},
    posture={'df.interface_key.A_STANCE'},
    sneaking={'df.interface_key.A_SNEAK'},
    movement={'df.interface_key.A_MOVEMENT','df.global.game.main_interface.adventure.movement_options.open',
        'df.global.game.main_interface.adventure.movement_options.scroll_gait','df.gait_type.WALK'},
    environment={'dfhack.buildings.findAtTile'},
    unit_health={{path='df.unit.find',type='function'},'dfhack.units.isVisible','dfhack.units.isHidden'},
    strike={'df.unit_action_type.Attack',{path='df.unit.find',type='function'},'df.interface_key.QUICK_ATTACK','df.interface_key.HEAVY_ATTACK',
        'df.interface_key.WILD_ATTACK','df.interface_key.PRECISE_ATTACK','df.interface_key.CHARGE_ATTACK',
        'df.interface_key.MULTI_ATTACK','dfhack.timeout'},
    campfire={'df.adventure_environment_pickup_make_campfirest.is_instance','df.tiletype_material.CAMPFIRE'},
    heating={'df.interface_key.A_INTERACT','df.adventure_item_interact_heat_from_tilest.is_instance'},
    filling={'df.interface_key.A_INTERACT','df.adventure_item_interact_fill_with_materialst.is_instance',
        'dfhack.matinfo.decode','dfhack.items.getCapacity'},
    rest={'df.interface_key.A_SLEEP','df.interface_key.A_TRAVEL_SLEEP','df.interface_key.A_SLEEP_SLEEP',
        'df.interface_key.A_SLEEP_WAIT','df.interface_key.A_SLEEP_DAWN','df.interface_key.SELECT',
        'df.interface_key.ADVENTURE_LIST_SCROLL_UP','df.interface_key.ADVENTURE_LIST_SCROLL_DOWN',
        'df.interface_key.ADVENTURE_LIST_SCROLL_PAGEUP','df.interface_key.ADVENTURE_LIST_SCROLL_PAGEDOWN',
        'df.global.game.main_interface.adventure.sleep.open','df.global.adventure.sleep_hours',
        'df.global.adventure.sleeping','df.global.adventure.sleep_interrupt'},
    rest_dawn={'df.interface_key.A_SLEEP_DAWN','df.game_type.ADVENTURE_MAIN',
        {path='df.global.adventure.sleep_until_dawn',type='boolean'},
        {path='df.global.adventure.started_sleep_at_dawn',type='boolean'},
        'df.global.cur_year_tick','df.global.cur_season_tick','df.global.world.world_data.world_width'},
}
local vectors={option_current=true,option=true,conv_choice_info=true,select_option=true,
    unit_choice=true,move_choice=true,aim_mod=true}
local function compatible(path,v,expected)
    local name=path:match('([^.]+)$')
    if expected=='vector' or (not expected and vectors[name]) then
        return (type(v)=='table' or type(v)=='userdata') and value(function()return #v>=0 end)==true
    end
    if expected then return type(v)==expected end
    if path:sub(1,7)=='dfhack.' or name=='is_instance' then return type(v)=='function' end
    if name=='open' then return type(v)=='boolean' end
    return type(v)=='number'
end
function M.capabilities()
    local out={format='runtime_capabilities',schema_version=1,features={},panels=M.panels(),
        runtime={df_version=value(dfhack.getDFVersion),dfhack_version=value(dfhack.getDFHackVersion),
            os=value(dfhack.getOSType),pe_timestamp=value(function()return dfhack.internal.getPE()end)},
        basis='Dependency probes check readable native symbols, not future-version behavioral compatibility'}
    for name,paths in pairs(requirements) do
        local missing,invalid=h.array(),h.array()
        for _,dependency in ipairs(paths) do
            local path=type(dependency)=='table' and dependency.path or dependency
            local expected=type(dependency)=='table' and dependency.type or nil
            local v=value(function()return resolve(path)end)
            if v==nil then missing[#missing+1]=path
            elseif not compatible(path,v,expected) then invalid[#invalid+1]={path=path,actual_type=type(v)} end
        end
        out.features[name]={dependencies_present=#missing==0 and #invalid==0}
        if #missing>0 then out.features[name].missing=missing end
        if #invalid>0 then out.features[name].invalid=invalid end
    end
    out.adapters={native_path={method='native_movement_command',
        dependencies_present=out.features.native_path.dependencies_present,
        completion='DF computes/follows the path; arrival verified, controller watch changes pause for shared policy evaluation',
        limitation='Visible reachable endpoints on the loaded map; arrival radii and semantic approaches share this adapter. Explicit route constraints retain the observed-route adapter. Cancellation stops future path steps; a native Move already submitted may settle.'},
        inventory=h.bindings.support(),conversation={
        method=h.bindings.conversation_supported({kind='conversation'}) and 'native_hotkey' or 'ascii_ordered_labels',
        indexing='Native option indices for target and tact pickers; native title-line offsets for topics',
        tacts={dependencies_present=out.features.conversation_tacts.dependencies_present,
            method=out.features.conversation_tacts.dependencies_present and h.bindings.support().native_hotkey_available
                and 'native_hotkey' or 'unavailable'}},
        movement={method=h.bindings.list_supported({kind='movement'}) and 'native_hotkey' or 'unavailable',
            indexing='native_page',limitation='Uses the current native gait mode and OPTION1..20; does not switch locomotion mode'},
        ground_options={method=h.bindings.list_supported({kind='option_list'}) and 'native_hotkey' or 'ascii_ordered_labels'},
        rest={method=h.bindings.support().native_hotkey_available and 'native_keys' or 'unavailable',
            completion='Explicit hours or the configured next local dawn verified against native calendar progress',
            until_dawn=out.features.rest_dawn.dependencies_present and h.bindings.support().native_hotkey_available,
            dawn_validation='Native clock/completion code and fixtures; successful live until-dawn completion not yet verified',
            limitation='Dawn requires a visible sky and the verified main-adventure clock model; interrupted rest is not restarted'},
        saving={method=h.bindings.support().native_hotkey_available and 'native_layout_and_keys' or 'unavailable',
            context='MAIN_ADVENTURE',
            completion='Native save closes and the requested world file is newly written',
            limitation='Options has mouse-only selection; geometry is verified for this build. Save-and-quit and timeline decisions are not save_game objectives'},
        combat={method=h.bindings.combat_supported({kind='combat',mode='UNIT_CHOICE'}) and 'native_keys' or 'ascii_ordered_labels',
            native_modes={'UNIT_CHOICE','CONFIRM','MOVE_CHOICE','AIM_TARGET','AIM_ATTACK'},
            strike='Explicit single aimed melee attempt, native style keys and bounded action-phase observer',
            limitation='Charge, multiattack, wrestling, defense and ranged completion remain unsupported'}}
    if h.calculations then
        local r=out.runtime
        local supported=h.calculations.supported(r.df_version,r.os,r.pe_timestamp)
        out.calculations={available=supported,model=h.calculations.build.model}
        if not supported then out.calculations.reason='No verified pure calculation model for this executable' end
    end
    return out
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
