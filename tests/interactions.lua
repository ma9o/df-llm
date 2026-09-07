-- Isolated native-menu fixtures; no reads/writes to the live world's state.
local source,bindings_source=...
local function vector(values)
    local out={_count=#values}
    for i,v in ipairs(values) do out[i-1]=v end
    return setmetatable(out,{__len=function(v)return v._count end})
end
local function native_ipairs(v)
    if type(v)=='table' and rawget(v,'_count') then
        local i=-1
        return function()i=i+1;if i<v._count then return i,v[i] end end
    end
    return ipairs(v)
end
local c={open=false}
local a={open=false}
local activities={}
local env=setmetatable({ipairs=native_ipairs,df={
    global={game={main_interface={adventure={conversation=c,attack=a}}}},
    interface_key={OPTION1=1,OPTION2=2},
    talk_choice_type={[4]='AskAboutCurrentState'},adventure_option_type={[7]='TALK_NEW_CONVERSATION'},
    adventure_interface_attack_mode_type={[0]='UNIT_CHOICE',[1]='CONFIRM',[2]='MOVE_CHOICE'},
    attack_move_choice_type={[0]='STRIKE'},conversation_tact_type={[0]='Persuade',[1]='Intimidate'},
    activity_entry={find=function(id)return activities[id]end},
    activity_event_conversationst={is_instance=function(_,e)return e.conversation==true end},
    new=function()return {value='',delete=function()end}end,
},dfhack={getDFVersion=function()return 'v0.53.16 win64 STEAM'end,
    internal={md5=function(s)return 'hash-'..#s end},units={getReadableName=function(u)return u.name end}}},
    {__index=_ENV})
local h={array=function()return {}end,text=function(s)return s end}
h.bindings=assert(load(bindings_source,'native-ui-fixture','t',env))(h)
local reader=assert(load(source,'interactions-fixture','t',env))(h)
local passed=0
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));passed=passed+1
    names[#names+1]=name
end
test('closed interfaces preserve false',function()
    assert(reader.conversation({rows={}}).open==false)
    assert(reader.combat({rows={}}).open==false)
end)
c.open=true;c.selecting_conversation=false;c.selecting_tact=false;c.conv_string_filter=''
c.entering_conv_string_filter=false;c.choice_scroll_position=0
c.conv_act={id=5};c.conv_actce={event_id=7,conversation=true,participants=vector({{unit_id=1},{unit_id=2}}),turns=vector({}),floor_holder=-1}
c.conv_act.events=vector({c.conv_actce});activities[5]=c.conv_act
c.conv_choice_info=vector({{title={text=vector({{value='Ask how listener is feeling'}})},choice={type=4},orig_index=3}})
local ui={rows={{y=20,text='    a Ask how listener is feeling'}}}
test('native topic ID and ASCII binding',function()
    local r=reader.conversation(ui)
    assert(r.options[1].native_type=='AskAboutCurrentState')
    assert(r.options[1].visible and r.options[1].click.y==20 and not r.options[1].selection)
    assert(r.participants[1]==1 and r.participants[2]==2)
    assert(reader.option(r.options[1].id,ui).id==r.options[1].id)
end)
test('native conversation event and empty turn cursor preserve zero',function()
    local r=reader.conversation(ui)
    assert(r.activity_event_id==7 and r.activity.turn_count==0 and r.activity.floor_holder==-1)
    assert(r.activity.available and #r.activity.turns==0)
end)
test('targeted conversation history survives a closed interface',function()
    c.open=false
    c.conv_actce.turns=vector({{speaker=1,type=4,year=100,ticks=0},{speaker=2,type=4,year=100,ticks=1}})
    local r=reader.activity(5,7)
    assert(r.available and r.turn_count==2 and r.turns[1].index==0 and r.turns[2].speaker_id==2)
    assert(r.turns[1].ticks==0 and r.turns[1].native_type=='AskAboutCurrentState')
    assert(reader.activity(5,0).available==false and reader.activity(99,7).available==false)
    c.conv_actce.turns=vector({});c.open=true
end)
test('bounded native history reports omitted turns',function()
    local values={};for _=1,130 do values[#values+1]={speaker=2,type=4,year=100,ticks=0} end
    c.conv_actce.turns=vector(values)
    local r=reader.activity(5,7)
    assert(r.turn_count==130 and r.turns_omitted==2 and #r.turns==128 and r.turns[1].index==2)
    c.conv_actce.turns=vector({})
end)
test('unrendered topics retain IDs without guessed keys',function()
    assert(not reader.conversation({rows={}}).options[1].visible)
end)
test('duplicate rendered labels cannot bind a click',function()
    local r=reader.conversation({rows={{y=1,text='a Ask how listener is feeling'},{y=2,text='a Ask how listener is feeling'}}})
    assert(not r.options[1].visible and not r.options[1].click)
end)
test('line scroll offsets do not change native identity or visible label binding',function()
    local id=reader.conversation(ui).options[1].id
    c.choice_scroll_position=1
    local r=reader.conversation(ui)
    assert(r.options[1].id==id and r.options[1].visible)
    c.choice_scroll_position=0
end)
test('filter entry blocks native selection',function()
    c.entering_conv_string_filter=true
    local r=reader.conversation(ui)
    assert(r.selection_unavailable and not r.options[1].selection and not r.options[1].click)
    c.entering_conv_string_filter=false
end)
test('unknown tact binding is explicit',function()
    c.selecting_tact=true;c.tact_scroll_position=0;c.tact_list=vector({0})
    local r=reader.conversation(ui)
    assert(r.selection_unavailable and not r.options[1].visible and r.options[1].native_type=='Persuade')
    c.selecting_tact=false
end)
test('combat move maps only an explicit native choice',function()
    a.open=true;a.mode=2;a.attack_unit={id=9};a.move_choice=vector({0});a.scroll_position_move_choice=0
    a.allow_strike=true;a.allow_wrestle=false;a.selected_bp=-1;a.selected_item_id=-1
    local r=reader.combat({rows={{y=10,text='a Strike'}}})
    assert(r.options[1].id=='combat-move:9:STRIKE' and r.options[1].visible)
    assert(r.allow_wrestle==false)
end)
test('confirmation without verified native keys stays explicit',function()
    a.mode=1;a.confirm_unit={id=9};a.custom_combat={aim_mod=vector({})}
    local r=reader.combat(ui)
    assert(r.mode=='CONFIRM' and #r.options==2 and r.selection_unavailable)
end)
test('combat modes never read inactive native pointers or vectors',function()
    local saved={};for k,v in pairs(a)do saved[k]=v;a[k]=nil end
    setmetatable(a,{__index=function(_,k)error('Inactive native field: '..k)end})
    a.open=true;a.mode=1;a.confirm_unit={id=99};a.always_do_something=false
    local r=reader.combat(ui)
    assert(r.target_unit_id==99 and r.confirm_unit_id==99 and r.aim_modifiers==nil)
    a.mode=0;a.confirm_unit=nil;a.unit_choice=vector({{id=98,name='Opponent'}});a.scroll_position_unit_choice=0;a.scrolling_unit_choice=false
    r=reader.combat(ui)
    assert(r.target_unit_id==nil and #r.options==1 and r.options[1].unit_id==98)
    setmetatable(a,nil);for k in pairs(a)do a[k]=nil end;for k,v in pairs(saved)do a[k]=v end
end)
test('verified combat target and confirmation options require no rendered labels',function()
    for i=1,20 do env.df.interface_key['OPTION'..i]=81+i end
    env.df.interface_key.A_ATTACK_CONFIRM=347;env.df.interface_key.LEAVESCREEN=5
    a.mode=0;a.unit_choice=vector({{id=8,name='Same name'},{id=9,name='Same name'}})
    a.scroll_position_unit_choice=0
    local r=reader.combat({rows={}})
    assert(r.options[2].selection.scroll_to==1 and not r.options[2].click)
    a.mode=1;a.confirm_unit={id=9};a.attack_unit={id=777};a.always_do_something=false
    r=reader.combat({rows={}})
    assert(r.target_unit_id==9 and not r.selection_unavailable and #r.options==2)
    assert(h.bindings.selection_key(r,r.options[2])=='LEAVESCREEN')
    assert(h.bindings.prepare(r,r.options[2])==nil)
    a.always_do_something=true
    r=reader.combat({rows={}})
    assert(r.always_do_something and r.options[1].label=='Confirm and attack now')
    a.always_do_something=false
    a.always_do_something=nil
    r=reader.combat(ui)
    assert(r.selection_unavailable=='Native confirmation outcome is unavailable')
    assert(not r.options[1].selection and r.options[1].label=='Confirm (native outcome unavailable)')
    a.always_do_something=false
    -- Subsequent compatibility fixtures start with the original key set.
    for i=3,20 do env.df.interface_key['OPTION'..i]=nil end
end)
test('HF subjects require a supported topic and matching native figure name',function()
    env.df.talk_choice_type[9]='AskAboutHf'
    env.df.historical_figure={find=function(id)if id==0 then return {name='Ilosp Seamdrummed'} end end}
    env.dfhack.translation={translateName=function(name)return name end}
    local saved=c.conv_choice_info
    c.conv_choice_info=vector({{title={text=vector({{value='Ask about the human Ilosp Seamdrummed'}})},
        choice={type=9,invocation_target_hfid=0},orig_index=0}})
    local o=reader.conversation({rows={}}).options[1]
    assert(o.subject_hf_id==0 and o.subject_name=='the human Ilosp Seamdrummed')
    assert(reader.option(o.handle,{rows={}}).id==o.id)
    c.conv_choice_info[0].choice.invocation_target_hfid=99
    assert(reader.conversation({rows={}}).options[1].subject_hf_id==nil)
    local reads=0
    c.conv_choice_info[0].choice=setmetatable({type=4},{__index=function()reads=reads+1;error('Untagged payload')end})
    assert(reader.conversation({rows={}}).options[1].subject_hf_id==nil and reads==0)
    c.conv_choice_info=saved
end)
test('native topic slots follow multiline titles and partial first rows without ASCII',function()
    for i=1,20 do env.df.interface_key['OPTION'..i]=81+i end
    local saved=c.conv_choice_info
    c.conv_choice_info=vector({
        {title={text=vector({{value='same'},{value='long'},{value='label'},{value='wrap'}})},choice={type=4},orig_index=0},
        {title={text=vector({{value='same truncated label'}})},choice={type=4},orig_index=1},
        {title={text=vector({{value='same truncated label'},{value='wrap'}})},choice={type=4},orig_index=2}})
    c.choice_scroll_position=2
    local r=reader.conversation({rows={}})
    assert(r.options[1].selection.scroll_to==0 and not r.options[1].selection.key_index)
    assert(r.options[2].selection.scroll_to==6 and r.options[2].selection.key_index==0)
    assert(r.options[3].selection.scroll_to==9 and r.options[3].selection.key_index==1)
    assert(h.bindings.selection_key(r,r.options[3])=='OPTION2')
    assert(not r.options[2].click and not r.options[3].click)
    c.choice_scroll_position=0;c.conv_choice_info=saved
end)
test('native conversation picker distinguishes duplicate labels by native index',function()
    local function option(id)
        return {unit_id=id,getType=function()return 7 end,getName=function(_,s)s.value='same truncated label' end}
    end
    c.selecting_conversation=true;c.select_scroll_position=0
    c.select_option=vector({option(1),option(2)})
    local r=reader.conversation({rows={}})
    assert(r.options[1].unit_id==1 and r.options[2].unit_id==2)
    assert(r.options[2].selection.scroll_to==1 and h.bindings.selection_key(r,r.options[2])=='OPTION2')
    assert(not r.options[1].click and not r.options[2].click)
    c.selecting_conversation=false
end)
test('conversation modes do not read inactive activity or tact pointers',function()
    local saved={};for k,v in pairs(c)do saved[k]=v end
    local reads=0
    local poison=setmetatable({},{__index=function()reads=reads+1;error('Inactive native pointer')end})
    c.tact_cci=poison
    assert(reader.conversation({rows={}}).activity_id==5 and reads==0)
    c.selecting_conversation=true;c.conv_act=poison;c.conv_actce=poison;c.conv_choice_info=poison
    local r=reader.conversation({rows={}})
    assert(r.activity_id==nil and r.activity==nil and #r.participants==0 and reads==0)
    for k in pairs(c)do c[k]=nil end;for k,v in pairs(saved)do c[k]=v end
end)
test('native tact choices bind by index and retain their pending topic identity',function()
    env.df.talk_choice_type[227]='FishForPlots'
    local saved=c.conv_choice_info
    c.conv_choice_info=vector({{title={text=vector({{value='Ask about plots'}})},choice={type=227},orig_index=12}})
    local topic=reader.conversation({rows={}}).options[1]
    assert(topic.tact_required and topic.native_index==12)
    c.selecting_tact=true;c.tact_cci=c.conv_choice_info[0];c.tact_list=vector({0,1})
    c.tact_scroll_position=0;c.tact_scrolling=false
    local r=reader.conversation({rows={}})
    assert(r.tact_topic.id==topic.id and r.tact_topic_index==12 and not r.selection_unavailable)
    assert(r.options[1].native_type=='Persuade' and r.options[2].native_type=='Intimidate')
    assert(h.bindings.selection_key(r,r.options[2])=='OPTION2' and not r.options[2].click)
    local first=r.options[1].handle
    c.tact_cci.orig_index=13
    assert(reader.conversation({rows={}}).options[1].handle~=first)
    c.tact_scrolling=true
    assert(reader.conversation({rows={}}).selection_unavailable)
    c.tact_scrolling=false;c.selecting_tact=false;c.conv_choice_info=saved
end)
test('verified interrogation navigation declares its native child topics',function()
    env.df.talk_choice_type[225]='Interrogate'
    local saved=c.conv_choice_info
    c.conv_choice_info=vector({{title={text=vector({{value='Investigate or interrogate'}})},choice={type=225},orig_index=0}})
    local r=reader.conversation({rows={}})
    assert(r.options[1].opens_topics[1]=='FishForMaster' and r.options[1].opens_topics[2]=='FishForPlots')
    assert(r.options[1].tact_required==false)
    c.conv_choice_info=saved
end)
test('unknown or missing pending tact topic cannot become a selectable choice',function()
    c.selecting_tact=true
    for _,choice in ipairs({{}, {title={text=vector({})},choice={type=4},orig_index=0}}) do
        c.tact_cci=choice
        local r=reader.conversation({rows={}})
        assert(r.selection_unavailable and not r.options[1].selection and not r.options[1].click)
    end
    c.selecting_tact=false
end)
return {passed=passed,tests=names,game_inputs=0}
