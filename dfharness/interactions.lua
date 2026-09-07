--@ module=true
--luacheck: globals factory
local function build(...)
-- Native interaction identities and shared input adapters.
-- No conversation topic, opponent, attack, or confirmation is selected here.
local h=...
local array,text=h.array,h.text
local bindings=h.bindings
local M={}
local binding=bindings.binding
local function participants(event)
    local ids=array()
    if event then for _,p in ipairs(event.participants) do
        if #ids>=100 then break end
        ids[#ids+1]=p.unit_id
    end end
    return ids
end
local function optional(fn) local ok,v=pcall(fn);if ok then return v end end
local function bounded(out,values,convert)
    if #values>500 then out.truncated=true;out.total=#values end
    for i=0,math.min(#values,500)-1 do out.options[#out.options+1]=convert(values[i],i) end
end
local function activity_summary(activity,event)
    local out={available=true,activity_id=activity.id,activity_event_id=event.event_id,
        participants=participants(event),turn_count=#event.turns,floor_holder=event.floor_holder,
        turns=array(),turns_omitted=math.max(0,#event.turns-128)}
    for i=out.turns_omitted,#event.turns-1 do
        local turn=event.turns[i]
        -- Only common utterance fields. Its untagged topic union stays unread.
        out.turns[#out.turns+1]={index=i,speaker_id=turn.speaker,native_type=df.talk_choice_type[turn.type],
            year=turn.year,ticks=turn.ticks}
    end
    return out
end
local function topic_info(info,activity_id,index)
    local lines={}
    for _,line in ipairs(info.title.text) do lines[#lines+1]=text(line.value) end
    local label=table.concat(lines,' ')
    local kind=info.choice and df.talk_choice_type[info.choice.type] or 'unknown'
    -- Keep untagged union payloads unread. The native topic and original index
    -- also identify the pending topic while its tact list owns the interface.
    local id='dialogue:'..tostring(activity_id)..':'..kind..':'..info.orig_index..':'..dfhack.internal.md5(label)
    local entry={id=id,index=index,native_index=info.orig_index,kind='topic',native_type=kind,label=label}
    if bindings.support().native_hotkey_available then
        -- Installed feed 0x886b16: only these native types open a tact picker.
        entry.tact_required=kind=='FishForMaster' or kind=='FishForPlots'
        -- Installed apply handler 0x8a2f61 only changes the native conversation
        -- menu and rebuilds its choices. Following this edge speaks no line.
        if kind=='Interrogate' then entry.opens_topics={'FishForMaster','FishForPlots'} end
    end
    -- advtools/convo uses this union member for HF whereabouts. Verify the
    -- referenced figure's translated name against the native label as well.
    if kind=='AskAboutHf' or kind=='AskForDirectionsToHf' then
        local target=optional(function()
            local hf_id=info.choice.invocation_target_hfid
            local hf=df.historical_figure.find(hf_id)
            local name=hf and text(dfhack.translation.translateName(hf.name,true))
            if name and #name>0 and label:find(name,1,true) then return hf_id end
        end)
        if target then
            entry.subject_hf_id=target;entry.id=entry.id..':hf:'..target
            entry.subject_name=label:gsub('^Ask about ',''):gsub('^Ask for the whereabouts of ','')
        end
    end
    return entry
end
function M.activity(activity_id,event_id)
    local activity=df.activity_entry.find(activity_id)
    if activity then for _,event in ipairs(activity.events) do
        if event.event_id==event_id and df.activity_event_conversationst:is_instance(event) then
            return activity_summary(activity,event)
        end
    end end
    return {available=false,activity_id=activity_id,activity_event_id=event_id,
        reason='The observed conversation activity/event is no longer available'}
end
function M.conversation(ui)
    local c=df.global.game.main_interface.adventure.conversation
    if not c.open then return {open=false} end
    local out={open=true,kind='conversation',selecting=c.selecting_conversation,selecting_tact=c.selecting_tact,
        entering_filter=c.entering_conv_string_filter,filter=text(c.conv_string_filter),
        tact=optional(function()return df.conversation_tact_type[c.conv_tact]end),
        participants=array(),
        options=array(),choices=array(),scroll=c.selecting_conversation and c.select_scroll_position or c.choice_scroll_position}
    out.scrolling=c.choice_scrolling
    if c.selecting_conversation then out.scrolling=c.select_scrolling end
    -- The target picker does not own the previous conversation pointers. The
    -- tact choice pointer is likewise meaningful only while choosing a tact.
    -- Catching a Lua error cannot protect a read through a freed C++ object.
    if not c.selecting_conversation and c.conv_act and c.conv_actce then
        out.activity_id=c.conv_act.id
        out.participants=participants(c.conv_actce)
        out.activity=activity_summary(c.conv_act,c.conv_actce)
        out.activity_event_id=c.conv_actce.event_id
    end
    if c.selecting_tact then
        out.tact_topic=optional(function()return topic_info(c.tact_cci,out.activity_id)end)
        out.tact_topic_index=out.tact_topic and out.tact_topic.native_index
        out.scroll=c.tact_scroll_position
        out.scrolling=c.tact_scrolling
        bounded(out,c.tact_list,function(tact,i)
            local name=df.conversation_tact_type[tact]
            return bindings.bind({id='tact:'..tostring(out.activity_id)..':'..tostring(out.tact_topic_index)..':'..tact,
                index=i,kind='tact',native_type=name or tostring(tact),label=name},i,out.scroll,
                bindings.conversation_supported(out))
        end)
        if not out.tact_topic or not out.tact_topic.tact_required then
            out.selection_unavailable='The native topic for this tact choice is unavailable or unverified'
        elseif not bindings.conversation_supported(out) then
            out.selection_unavailable='No verified conversation tact input binding for this build'
        end
    elseif c.selecting_conversation then
        bounded(out,c.select_option,function(option,i)
            local unit_id=optional(function()return option.unit_id end)
            local p=participants(optional(function()return option.conv_actev end))
            local label=bindings.named(option)
            local kind=df.adventure_option_type[option:getType()]
            local id='conversation-target:'..kind..':'..tostring(unit_id)..':'..table.concat(p,',')..':'..dfhack.internal.md5(label or '')
            return binding({id=id,index=i,kind='target',label=label,unit_id=unit_id,participants=p},
                i,out.scroll,ui,bindings.conversation_supported(out))
        end)
    else
        local line_start,key_index=0,0
        bounded(out,c.conv_choice_info,function(info,i)
            local entry=topic_info(info,out.activity_id,i)
            -- The native feed counts title.text lines plus two separator lines.
            -- OPTION numbering starts at the first title whose first text line
            -- is at/after the scroll offset. No ASCII label or pixel matching.
            local eligible=line_start+1>=out.scroll
            bindings.bind_topic(entry,out,line_start,eligible and key_index or nil)
            if eligible then key_index=key_index+1 end
            line_start=line_start+#info.title.text+2
            return entry
        end)
        out.choices=out.options -- retain the original observation field as an alias
    end
    if out.scrolling then
        out.selection_unavailable='Finish dragging the conversation scroll bar before selection'
    elseif c.entering_conv_string_filter then
        out.selection_unavailable='Finish entering the conversation filter before selecting an option'
    end
    if out.selection_unavailable then
        for _,o in ipairs(out.options) do o.selection=nil;o.click=nil;o.visible=nil end
    end
    return bindings.catalog(bindings.text_menu(out,ui))
end
function M.combat(ui)
    local a=df.global.game.main_interface.adventure.attack
    if not a.open then return {open=false} end
    local mode=df.adventure_interface_attack_mode_type[a.mode]
    local out={open=true,kind='combat',mode=mode,options=array(),scroll=0}
    -- Native modes retain inactive pointer/vector fields from earlier menus
    -- and even earlier worlds. pcall cannot make a freed C++ pointer safe. Read
    -- only the data owned by the current mode, never fall back to another target.
    local targeted={MOVE_CHOICE=true,AIM_TARGET=true,AIM_ATTACK=true,PARRY_CHOICE=true,
        BLOCK_CHOICE=true,DODGE_CHOICE=true,WRESTLE_GRASP=true,WRESTLE_MOVE=true}
    if mode=='CONFIRM' then
        out.confirm_unit_id=a.confirm_unit and a.confirm_unit.id or nil
        out.target_unit_id=out.confirm_unit_id
        out.always_do_something=a.always_do_something
    elseif targeted[mode] then
        out.target_unit_id=a.attack_unit and a.attack_unit.id or nil
        out.always_do_something=a.always_do_something
        out.can_jump_dodge=optional(function()return a.special_combat.can_jump_dodge end)
        out.allow_strike=a.allow_strike;out.allow_wrestle=a.allow_wrestle
    end
    if mode=='UNIT_CHOICE' then
        out.scroll=a.scroll_position_unit_choice
        out.scrolling=a.scrolling_unit_choice
        bounded(out,a.unit_choice,function(u,i)
            return binding({id='combat-unit:'..u.id,index=i,kind='target',unit_id=u.id,
                label=text(dfhack.units.getReadableName(u))},i,out.scroll,ui,bindings.combat_supported(out))
        end)
    elseif mode=='CONFIRM' then
        local known=type(out.always_do_something)=='boolean'
        local label=not known and 'Confirm (native outcome unavailable)'
            or (out.always_do_something and 'Confirm and attack now' or 'Confirm target and choose a move')
        for i,choice in ipairs({{'confirm','A_ATTACK_CONFIRM',label},{'cancel','LEAVESCREEN','Cancel'}})do
            local o=bindings.fixed({id='combat-confirm:'..tostring(out.target_unit_id)..':'..choice[1],
                index=i-1,kind='confirmation',native_type=choice[1],unit_id=out.target_unit_id,label=choice[3]},
                choice[2],out.target_unit_id~=nil and known)
            out.options[#out.options+1]=o
            if not o.selection then out.selection_unavailable='Combat confirmation keys are unverified for this build' end
        end
        if not known then out.selection_unavailable='Native confirmation outcome is unavailable' end
    elseif mode=='MOVE_CHOICE' then
        out.scroll=a.scroll_position_move_choice
        out.scrolling=a.scrolling_move_choice
        local labels={STRIKE='Strike',WRESTLE='Wrestle',PARRY='Parry',BLOCK='Block',DODGE_AWAY='Dodge away'}
        bounded(out,a.move_choice,function(kind,i)
            local name=df.attack_move_choice_type[kind]
            return binding({id='combat-move:'..tostring(out.target_unit_id)..':'..name,index=i,
                kind='move',native_type=name,label=labels[name]},i,out.scroll,ui,bindings.combat_supported(out))
        end)
    elseif mode=='AIM_TARGET' or mode=='AIM_ATTACK' then
        h.aim.menu(out)
    else
        -- Keep the native decision visible even where input bindings have not
        -- been verified. Never turn an arbitrary letter into a purported attack.
        out.selection_unavailable='No verified semantic selection binding for combat mode '..tostring(mode)
        if mode=='WRESTLE_GRASP' or mode=='WRESTLE_MOVE' then
            out.selected_body_part_id=a.selected_bp;out.selected_item_id=a.selected_item_id
        end
    end
    if out.scrolling then out.selection_unavailable='Finish dragging the combat list before selection' end
    return bindings.catalog(bindings.text_menu(out,ui))
end
function M.option(id,ui)
    for _,menu in ipairs({M.conversation(ui),M.combat(ui)}) do
        for _,option in ipairs(menu.options or {}) do if option.id==id or option.handle==id then return option,menu end end
    end
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
