-- Isolated interface adapters: no live units, inputs or UI writes.
local source=...
local inventory={open=true,context=1,scroll_position=0,option_current={}}
for i=1,60 do inventory.option_current[i]={id=i,title={text={'title'}}} end
local conversation={open=true,entering_conv_string_filter=false,selecting_tact=false,
    selecting_conversation=false,choice_scroll_position=0,conv_choice_info=inventory.option_current}
local version='v0.53.16 win64 STEAM'
local keys={};for i=1,20 do keys['OPTION'..i]=i end
local env=setmetatable({df={interface_key=keys,adventure_interface_inventory_context_type={DROP=1,INTERACT_LIST=8},global={game={main_interface={adventure={
    inventory=inventory,conversation=conversation}}}}},dfhack={getDFVersion=function()return version end}},
    {__index=_ENV})
local normalize_calls,max_scroll=0,40
local m=assert(load(source,'native-ui-fixture','t',env))({text=function(s)return s end,
    normalize_ui=function()
        normalize_calls=normalize_calls+1
        if #inventory.option_current>20 then
            inventory.scroll_position=math.min(inventory.scroll_position,max_scroll)
        end
        conversation.choice_scroll_position=math.min(conversation.choice_scroll_position,123)
    end})
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('nonfirst native options need no label or ASCII row',function()
    local o=m.binding({id='second'},1,0,{rows={}},true)
    assert(o.selection.method=='native_hotkey' and not o.click)
    assert(m.key(1,0)=='OPTION2')
end)
test('native bindings stop at OPTION20',function()
    assert(m.key(19,0)=='OPTION20')
    assert(not pcall(m.key,20,0))
    assert(m.bind({},20,0,true).selection.scroll_to==20)
    assert(not pcall(m.key,0,1))
end)
test('UI scroll writes the allowed offset only',function()
    local option=m.bind({id='item',index=48},48,0,true)
    local r=m.scroll({kind='inventory'},option)
    assert(inventory.scroll_position==40 and inventory.open and #inventory.option_current==60)
    assert(r.before==0 and r.requested==48 and r.effective==40 and r.field=='scroll_position')
    assert(normalize_calls==1)
end)
test('selection uses the effective offset after final page clamping',function()
    assert(m.key(48,inventory.scroll_position)=='OPTION9')
end)
test('native topic scrolling uses line offsets instead of item indices',function()
    local menu={kind='conversation'}
    local option=m.bind_topic({id='return',index=56},menu,168,nil)
    local r=m.scroll(menu,option)
    assert(r.requested==168 and r.effective==123 and conversation.choice_scroll_position==123)
    option.selection.key_index=15
    assert(m.selection_key(menu,option)=='OPTION16')
    conversation.choice_scroll_position=0
end)
test('filter editing and stale target indices cannot write scroll',function()
    local option=m.bind({id='topic',index=12},12,0,true)
    conversation.entering_conv_string_filter=true
    assert(not pcall(m.scroll,{kind='conversation'},option))
    assert(conversation.choice_scroll_position==0)
    conversation.entering_conv_string_filter=false
    option.index=100
    assert(not pcall(m.scroll,{kind='inventory'},option))
    assert(inventory.scroll_position==40)
end)
test('inactive conversation scroll flags do not block the active picker',function()
    conversation.selecting_conversation=true;conversation.select_option=inventory.option_current
    conversation.select_scroll_position=0;conversation.select_scrolling=false;conversation.choice_scrolling=true
    assert(pcall(m.scroll,{kind='conversation'},m.bind({index=1},1,0,true)))
    conversation.select_scrolling=true
    assert(not pcall(m.scroll,{kind='conversation'},m.bind({index=1},1,0,true)))
    conversation.selecting_conversation=false;conversation.select_scrolling=false;conversation.choice_scrolling=false
end)
test('tact scrolling uses native item indices and ignores inactive topic scrolling',function()
    conversation.selecting_tact=true;conversation.tact_list={0,1};conversation.tact_scroll_position=9
    conversation.tact_scrolling=false;conversation.choice_scrolling=true
    local menu={kind='conversation',selecting_tact=true}
    assert(m.conversation_supported(menu))
    local option=m.bind({index=1},1,9,true)
    local r=m.scroll(menu,option)
    assert(r.field=='tact_scroll_position' and r.probe==2 and r.maximum==0 and r.effective==0)
    menu.scroll=r.effective
    assert(m.selection_key(menu,option)=='OPTION2')
    conversation.tact_scrolling=true
    assert(not pcall(m.scroll,menu,option))
    conversation.selecting_tact=false;conversation.tact_scrolling=false;conversation.choice_scrolling=false
end)
test('unverified menu families cannot write native scroll',function()
    local option=m.bind({index=4},4,0,true)
    assert(not pcall(m.scroll,{kind='combat'},option))
    assert(not pcall(m.scroll,{kind='option_list'},option))
end)
test('combat picker and move lists share verified native bounds',function()
    local panel={open=true,unit_choice={{},{},{},{},{},{}},move_choice={{},{},{},{},{},{}}}
    env.df.global.game.main_interface.adventure.attack=panel
    env.df.adventure_interface_attack_mode_type={[0]='UNIT_CHOICE',[2]='MOVE_CHOICE'}
    for _,pair in ipairs({{0,'UNIT_CHOICE','scroll_position_unit_choice'},{2,'MOVE_CHOICE','scroll_position_move_choice'}})do
        panel.mode=pair[1];panel[pair[3]]=3
        local menu={kind='combat',mode=pair[2]}
        local r=m.scroll(menu,m.bind({index=3},3,0,m.combat_supported(menu)))
        assert(r.effective==0 and r.maximum==0 and m.key(3,r.effective)=='OPTION4')
    end
    panel.mode=1
    assert(not pcall(m.scroll,{kind='combat',mode='UNIT_CHOICE'},m.bind({index=1},1,0,true)))
    panel.open=false
end)
test('single-page lists ignore stale stored offsets in every verified context',function()
    assert(m.inventory_supported(1) and m.inventory_supported(8) and not m.inventory_supported(100))
    local previous=inventory.option_current
    inventory.option_current={{},{},{},{},{},{}}
    for _,context in ipairs({1,8})do
        inventory.context=context;inventory.scroll_position=3
        local option=m.bind({index=3},3,0,true)
        local r=m.scroll({kind='inventory'},option)
        assert(r.probe==6 and r.probe_result==6 and r.maximum==0 and inventory.scroll_position==0)
        assert(m.key(option.index,r.effective)=='OPTION4')
    end
    inventory.option_current=previous;inventory.context=1;inventory.scroll_position=40
end)
test('aim-target scroll bounds use the live count instead of allocation length',function()
    local panel=env.df.global.game.main_interface.adventure.attack
    panel.open=true;panel.mode=3;panel.scroll_position_aim_target=5;panel.scrolling_aim_target=false
    env.df.adventure_interface_attack_mode_type[3]='AIM_TARGET'
    local storage={};for i=1,80 do storage[i]={} end
    env.df.global.world={attack_chance_info={target=storage,current_target_number=6}}
    local menu={kind='combat',mode='AIM_TARGET'}
    local r=m.scroll(menu,m.bind({index=4},4,0,m.combat_supported(menu)))
    assert(r.probe==6 and r.maximum==0 and r.effective==0)
    assert(not pcall(m.scroll,menu,m.bind({index=6},6,0,true)))
    panel.scrolling_aim_target=true
    assert(not pcall(m.scroll,menu,m.bind({index=1},1,0,true)))
    panel.open=false
end)
test('unknown inventory contexts and an active drag cannot adjust scroll',function()
    local option=m.bind({index=3},3,0,true)
    inventory.context=100
    assert(not pcall(m.scroll,{kind='inventory'},option) and inventory.scroll_position==40)
    inventory.context=1;inventory.scrolling=true
    assert(not pcall(m.scroll,{kind='inventory'},option) and inventory.scroll_position==40)
    inventory.scrolling=false
end)
test('OPTION enums do not imply that all twenty options fit on the page',function()
    max_scroll=5
    local r=m.scroll({kind='inventory'},m.bind({index=15},15,0,true))
    assert(r.requested==15 and r.effective==5 and m.key(15,r.effective)=='OPTION11')
    max_scroll=40
end)
test('unsupported builds retain isolated text adapter',function()
    version='different build'
    local o=m.binding({label='Some choice'},0,0,{rows={{y=5,text='a Some choice'}}},true)
    assert(not o.selection and o.visible and o.click.y==5)
    local duplicate=m.binding({label='Some choice'},0,0,
        {rows={{y=5,text='a Some choice'},{y=7,text='a Some choice'}}},true)
    assert(not duplicate.visible)
end)
test('truncated duplicate names align to a unique native ordered page',function()
    local menu={options={{label='Continue conversation with the Human lord Cobar'},
        {label='Continue conversation with the Human Peddler Kusut'},
        {label='Continue conversation with the Human Peddler Lam'},
        {label='Shout out to everybody'},{label='Assume an identity'}}}
    m.text_menu(menu,{rows={
        {y=1,text='a Continue conversation with the Human lord ...'},
        {y=4,text='b Continue conversation with the Human Peddl...'},
        {y=7,text='c Continue conversation with the Human Peddl...'},
        {y=10,text='d Shout out to everybody'},{y=13,text='e Assume an identity'}}})
    assert(menu.options[2].visible and menu.options[2].click.y==4)
    assert(menu.options[3].visible and menu.options[3].click.y==7)
end)
test('a lone truncated row never rebinds multiple native options',function()
    local menu={options={{label='Ask about the human First'},{label='Ask about the human Second'}}}
    m.text_menu(menu,{rows={{y=1,text='a Ask about the human ...'}}})
    for _,o in ipairs(menu.options) do assert(not o.click and o.selection_unavailable) end
    m.text_menu(menu,{rows={{y=1,text='a Ask about the human First'}}})
    assert(menu.options[1].visible and not menu.options[1].selection_unavailable)
    assert(not menu.options[2].visible and not menu.options[2].selection_unavailable)
end)
test('duplicate shortcut labels cannot fabricate an ordered page',function()
    local menu={options={{label='Continue conversation with First'},{label='Continue conversation with Second'}}}
    m.text_menu(menu,{rows={{y=1,text='a Continue conversation ...'},
        {y=3,text='a Continue conversation ...'}}})
    assert(not menu.options[1].click and not menu.options[2].click)
end)
test('short handles survive scrolling but never rebind changed option sets',function()
    local menu={kind='conversation',activity_id=7,options={{id='a'},{id='b'}}}
    m.catalog(menu)
    local first,second=menu.options[1].handle,menu.options[2].handle
    menu.scroll=99;m.catalog(menu)
    assert(menu.options[1].handle==first and menu.options[2].handle==second)
    menu.options[1],menu.options[2]=menu.options[2],menu.options[1]
    m.catalog(menu)
    assert(menu.options[1].handle~=first and menu.options[1].handle~=second)
    local other={kind='conversation',activity_id=8,options={{id='a'},{id='b'}}}
    m.catalog(other);assert(other.options[1].handle~=first)
    for i=1,130 do m.catalog({kind='inventory',options={{id='unique:'..i}}}) end
    local old={kind='conversation',activity_id=7,options={{id='a'},{id='b'}}}
    m.catalog(old);assert(old.options[1].handle~=first)
    assert(#env.dfhack.df_llm_choices.order<=128)
end)
test('choice namespaces change across world loads and game process restarts',function()
    local menu={kind='inventory',options={{id='same-native-item'}}}
    env.dfhack.df_llm_session={world_epoch='first.0'}
    m.catalog(menu);local first=menu.options[1].handle
    env.dfhack.df_llm_session.world_epoch='first.1'
    m.catalog(menu);local second=menu.options[1].handle
    env.dfhack.df_llm_choices=nil;env.dfhack.df_llm_session.world_epoch='second.0'
    m.catalog(menu)
    assert(first~=second and menu.options[1].handle~=first and menu.options[1].handle~=second)
end)
return {passed=#names,tests=names,game_inputs=0}
