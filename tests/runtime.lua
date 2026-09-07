-- Isolated dependency and interface-discovery fixtures; no live game objects.
local source=...
local panels={inventory={open=false,option_current={},scroll_position=0},
    unfamiliar_panel={open=true},travel={hover_text_ax=0}}
local version='known'
local native_keys=false
local save_panel={open=false,do_manual_save=true,manual_save_timer=0}
local env=setmetatable({df={global={game={main_interface={adventure=panels,
    name_creator={open=true},help={open=false},options=save_panel}}},
    interface_key={A_STANCE=0}},dfhack={getDFVersion=function()return version end,
    getDFHackVersion=function()return 'test' end,getOSType=function()return 'test' end,
    internal={getPE=function()return 0 end}}},{__index=_ENV})
local m=assert(load(source,'runtime-fixture','t',env))({array=function()return {}end,text=function(s)return s end,
    bindings={support=function()return {method='test',native_hotkey_available=native_keys}end,list_supported=function()return true end,
        conversation_supported=function()return true end,combat_supported=function()return true end},
    calculations={build={model='test'},supported=function(v)return v=='known' end}})
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('closed false flags and new open panels are discovered without a registry edit',function()
    local r=m.panels()
    assert(r.available and r.flags.inventory==false and r.flags.unfamiliar_panel==true)
    assert(r.flags['main.name_creator']==true and r.flags.help==false)
    assert(#r.unclassified==1 and r.unclassified[1]=='travel')
end)
test('missing interfaces report unknown instead of a healthy empty screen',function()
    local saved=env.df.global.game
    env.df.global.game=nil
    local r=m.panels();assert(not r.available and r.reason)
    env.df.global.game=saved
end)
test('saving readiness reads only active options and preserves false',function()
    assert(m.saving()==false)
    save_panel.open=true;assert(m.saving()==true)
    save_panel.do_manual_save=false;assert(m.saving()==false)
    save_panel.manual_save_timer=1;assert(m.saving()==true)
    save_panel.open=false
end)
test('offloaded party activities stay busy beyond the local action timer',function()
    assert(m.army_activity(nil).present==false)
    env.df.army_flags={sleeping=0,waiting=1,composing=2,working=3}
    local army={id=99,travel_count=800,flags={[0]=false,true,false,false}}
    local r=m.army_activity(army)
    assert(r.available and r.active and r.remaining==800 and r.flags.sleeping==false and r.flags.waiting)
    army.flags[1]=false;army.travel_count=0;r=m.army_activity(army)
    assert(r.available and r.active==false and r.remaining==0)
    army.flags[2]=nil;r=m.army_activity(army)
    assert(not r.available and r.active==nil and r.reason)
end)
test('native zero enum values are valid dependencies',function()
    local r=m.capabilities()
    assert(r.features.posture.dependencies_present and r.runtime.pe_timestamp==0)
    assert(not r.features.core.dependencies_present and #r.features.core.missing>0)
    assert(r.calculations.available)
end)
test('declared dependency types preserve false and empty native text',function()
    save_panel.option={};save_panel.entering_manual_folder=false;save_panel.entering_manual_str=''
    save_panel.confirm_manual_overwrite=false
    env.df.interface_key.OPTIONS=0;env.df.interface_key.SELECT=1;env.df.interface_key.STRING_A000=707
    env.df.options_context_type={MAIN_ADVENTURE=0};env.df.main_menu_option_type={SAVE_AND_CONTINUE=2}
    env.dfhack.filesystem={}
    for _,name in ipairs({'getBaseDir','isdir','isfile','mtime'})do env.dfhack.filesystem[name]=function()end end
    assert(m.capabilities().features.saving.dependencies_present)
    save_panel.entering_manual_folder=0
    assert(not m.capabilities().features.saving.dependencies_present)
    save_panel.entering_manual_folder=false;save_panel.entering_manual_str=nil
    assert(not m.capabilities().features.saving.dependencies_present)
    save_panel.entering_manual_str=''
end)
test('native unit lookup is a typed function dependency, not an enum',function()
    env.df.unit={find=function()end}
    env.dfhack.units={isVisible=function()end,isHidden=function()end}
    assert(m.capabilities().features.unit_health.dependencies_present)
    env.df.unit.find=0
    assert(not m.capabilities().features.unit_health.dependencies_present)
    env.df.unit=nil;env.dfhack.units=nil
end)
test('optional tact dependencies validate native vectors and zero enums',function()
    env.df.conversation_tact_type={Persuade=0,Intimidate=1}
    env.df.talk_choice_type={FishForMaster=226,FishForPlots=227}
    panels.conversation={open=false,selecting_tact=false,tact_list={},tact_scrolling=false,tact_scroll_position=0}
    assert(m.capabilities().features.conversation_tacts.dependencies_present)
    assert(m.capabilities().adapters.conversation.tacts.method=='unavailable')
    native_keys=true
    assert(m.capabilities().adapters.conversation.tacts.method=='native_hotkey')
    panels.conversation.tact_list=0
    assert(not m.capabilities().features.conversation_tacts.dependencies_present)
    assert(m.capabilities().adapters.conversation.tacts.method=='unavailable')
    panels.conversation=nil;native_keys=false
end)
test('native announcement state distinguishes closed, zero, more and unavailable',function()
    env.df.global.world={status={temp_flag={adv_showing_announcements=false},popups={}}}
    local r=m.announcement();assert(r.available and r.open==false and r.lines==nil)
    local s=env.df.global.world.status
    s.temp_flag.adv_showing_announcements=true;s.temp_flag.adv_have_more=false
    s.adv_scroll_position=0;s.adv_announcement={}
    r=m.announcement();assert(r.available and r.open and r.more==false and r.scroll==0 and r.lines==0)
    s.temp_flag.adv_have_more=true;assert(m.announcement().more)
    s.temp_flag.adv_showing_announcements=nil
    r=m.announcement();assert(not r.available and r.reason and r.open==nil)
end)
test('queued popups remain visible when ordinary announcement flags are false',function()
    local s=env.df.global.world.status
    s.temp_flag.adv_showing_announcements=false
    local poison=setmetatable({},{__index=function()error('Inactive queued popup')end})
    s.popups=setmetatable({[0]={text='You feel uneasy.'},[1]=poison},{__len=function()return 2 end})
    local r=m.announcement()
    assert(r.available and r.open and r.native_kind=='popup' and r.count==2 and r.text=='You feel uneasy.')
    s.popups[0].text=false
    r=m.announcement();assert(not r.available and r.reason)
    s.popups=nil
    assert(not m.announcement().available)
    s.popups={};assert(m.announcement().open==false)
end)
test('native acknowledgement requires the exact supported context and key',function()
    local modal={kind='announcement',source='native'}
    env.df.interface_key.SELECT=0
    assert(m.acknowledgement_key(modal)==nil)
    native_keys=true;assert(m.acknowledgement_key(modal)=='SELECT')
    assert(m.acknowledgement_key({kind='help',source='native'})==nil)
    assert(m.acknowledgement_key({kind='announcement'})==nil)
    env.df.interface_key.SELECT=nil;assert(m.acknowledgement_key(modal)==nil)
    local popup={kind='announcement',source='native',native_kind='popup'}
    env.df.interface_key.CLOSE_MEGA_ANNOUNCEMENT=6
    assert(m.acknowledgement_key(popup)=='CLOSE_MEGA_ANNOUNCEMENT')
    env.df.interface_key.CLOSE_MEGA_ANNOUNCEMENT='wrong'
    assert(m.acknowledgement_key(popup)==nil)
    native_keys=false
end)
test('renamed or wrongly typed keys do not masquerade as supported inputs',function()
    env.df.interface_key.A_STANCE='wrong'
    local r=m.capabilities()
    assert(not r.features.posture.dependencies_present and #r.features.posture.invalid==1)
    env.df.interface_key.A_STANCE=nil
    assert(#m.capabilities().features.posture.missing==1)
    env.df.interface_key.A_STANCE=0
end)
test('unknown executable versions do not inherit calculation verification',function()
    version='updated'
    local r=m.capabilities();assert(not r.calculations.available and r.calculations.reason)
end)
return {passed=#names,tests=names,game_inputs=0}
