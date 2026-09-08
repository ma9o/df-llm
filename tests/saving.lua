-- Isolated native quicksave requests and file evidence; no real game inputs.
local source=...
local names={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name end
local a={open=false,context=6,do_manual_save=false,manual_save_timer=0,entering_manual_folder=false,
    confirm_manual_overwrite=false,entering_manual_str='',entering_timeline=false,doing_help=false,
    adv_retirement_confirm=false,adv_abandon_confirm=false,adv_quit_without_saving_confirm=false}
local function queue()return {count=7,resize=function(self,n)self.count=n end}end
a.saver={stage=51,substage=51,info={nemesis_save_file_id=queue(),nemesis_member_idx=queue(),
    units=queue(),cur_unit_chunk='old',cur_unit_chunk_num=9,units_offloaded=10}}
local root_ok,loaded,exists,modified=true,true,false,123
local input,screen={},{}
local env=setmetatable({dfhack_flags={module=false},df={global={game={main_interface={options=a}},
    adventure={menu=0,player_control_state=0}},viewscreen_dungeonmodest={is_instance=function(_,s)return s==screen end},
    ui_advmode_menu={Default=0},adventure_game_loop_type={TAKING_INPUT=0},save_substage={Initializing=0},
    options_context_type={MAIN_ADVENTURE=6,[6]='MAIN_ADVENTURE'}},
    dfhack={isMapLoaded=function()return loaded end,world={isAdventureMode=function()return true end},
        gui={getCurViewscreen=function()return screen end,getCurFocus=function()return {'dungeonmode/Default'}end},
        filesystem={getBaseDir=function()return '/native-data/' end,
            isdir=function(path)if path=='/native-data//save/' then return root_ok end;return exists end,
            isfile=function(path)assert(path=='/native-data//save/night/world.sav');return exists end,
            mtime=function()return modified end}}}, {__index=_ENV})
local function reset()
    a.open=false;a.do_manual_save=false;a.entering_manual_folder=false;a.confirm_manual_overwrite=false
    a.entering_manual_str='';a.adv_abandon_confirm=false;input={}
end
local m=assert(load(source,'quicksave-fixture','t',env))({array=function()return {}end,text=function(s)return s end,
    input=function(key)
        input[#input+1]=key
        if key=='OPTIONS' then a.open=true
        elseif key=='SELECT' then
            assert(a.entering_manual_folder and a.entering_manual_str=='night')
            if exists then a.confirm_manual_overwrite=true else a.do_manual_save=true end
        else error('Unexpected input '..key)end
    end})
test('quicksave stages the exact filename then delegates native validation without clicking or typing',function()
    m.submit({name='night'})
    assert(#input==2 and input[1]=='OPTIONS' and input[2]=='SELECT' and a.do_manual_save)
    assert(a.manual_save_timer==0 and not exists) -- Only a request, not proof of a write.
end)
test('an existing save blocks before opening any interface unless overwrite was delegated',function()
    reset();exists=true
    assert(not pcall(m.submit,{name='night'}));assert(#input==0 and not a.open)
    m.submit({name='night',overwrite=true})
    assert(a.do_manual_save and a.confirm_manual_overwrite and #input==2)
    assert(a.manual_save_timer==5 and a.saver.stage==0 and a.saver.substage==0)
    assert(a.saver.info.nemesis_save_file_id.count==0 and a.saver.info.nemesis_member_idx.count==0
        and a.saver.info.units.count==0 and a.saver.info.cur_unit_chunk==nil
        and a.saver.info.cur_unit_chunk_num==-1 and a.saver.info.units_offloaded==-1)
end)
test('unavailable world and unfinished native options cannot receive a save request',function()
    reset();exists=false;loaded=false
    assert(not pcall(m.submit,{name='night'}));assert(#input==0)
    loaded=true;a.open=true
    assert(not pcall(m.submit,{name='night'}));assert(#input==0)
    reset();a.adv_abandon_confirm=true
    assert(not pcall(m.submit,{name='night'}));assert(#input==1 and not a.do_manual_save)
end)
test('closed and saving phases do not inspect inactive option pointers',function()
    reset();a.option=setmetatable({},{__len=function()error('Inactive native options')end})
    assert(m.menu()==nil);a.open=true;a.do_manual_save=true
    local menu=m.menu();assert(menu.mode=='saving' and #menu.options==0)
end)
test('native data-root failures are unknown and reserved names never request input',function()
    reset();exists=true
    local f=m.file('night');assert(f.available and f.world_exists and f.world_mtime=='123')
    root_ok=false;f=m.file('night');assert(not f.available and f.world_exists==nil);root_ok=true
    modified=-1;assert(not m.file('night').available);modified=123
    for _,name in ipairs({'current','autosave 1','autosave 2','autosave 3','../save'})do assert(not pcall(m.submit,{name=name}))end
    assert(#input==0)
end)
return {passed=#names,tests=names,game_inputs=0}
