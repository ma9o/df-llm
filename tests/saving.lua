-- Isolated Options geometry, text input and native data-root fixtures.
local source=...
local function vector(values)
    local v={};for i,x in ipairs(values)do v[i-1]=x end
    return setmetatable(v,{__len=function()return #values end})
end
local a={open=true,context=6,option=vector({1,2,7,9,3,0}),text={text=vector({})},
    do_manual_save=false,manual_save_timer=0,entering_manual_folder=false,confirm_manual_overwrite=false,
    entering_manual_str='',entering_timeline=false,doing_help=false}
for _,f in ipairs({'fort_retirement_confirm','adv_retirement_confirm','fort_abandon_confirm',
    'adv_abandon_confirm','fort_quit_without_saving_confirm','adv_quit_without_saving_confirm'})do a[f]=false end
local supported,root_ok,modified=true,true,123
local inputs={}
local env=setmetatable({df={global={game={main_interface={options=a}}},
    interface_key={SELECT=1,STRING_A000=707},options_context_type={[6]='MAIN_ADVENTURE'},
    main_menu_option_type={[0]='RETURN',[1]='SAVE_AND_QUIT',[2]='SAVE_AND_CONTINUE',
        [3]='SETTINGS',[7]='ABANDON_ADVENTURER',[9]='QUIT_WITHOUT_SAVING'}},
    dfhack={filesystem={getBaseDir=function()return '/native-data/' end,
        isdir=function(path)assert(path:sub(1,13)=='/native-data/');return root_ok end,
        isfile=function(path)assert(path=='/native-data//save/night/world.sav');return true end,
        mtime=function()return modified end},getSavePath=function()error('Stale install-relative save path')end}},
    {__index=_ENV})
local m=assert(load(source,'saving-fixture','t',env))({array=function()return {}end,text=function(s)return s end,
    bindings={support=function()return {native_hotkey_available=supported}end,catalog=function(menu)return menu end,
        fixed=function(entry,key)entry.selection={method='native_key',key=key}end},
    input=function(key)
        inputs[#inputs+1]=key
        if key=='STRING_A000' then a.entering_manual_str=a.entering_manual_str:sub(1,-2)
        else a.entering_manual_str=a.entering_manual_str..string.char(tonumber(key:match('(%d+)$'))) end
    end})
local names={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name end
test('options geometry uses native order and dimensions without text rows',function()
    local menu=m.menu({width=180,height=77})
    assert(menu.options[2].native_type=='SAVE_AND_CONTINUE' and menu.options[2].click.y==34)
    assert(menu.options[2].click.x==89 and not menu.options[2].selection)
    menu=m.menu({width=140,height=60})
    assert(menu.options[2].click.x==69 and menu.options[2].click.y==26)
end)
test('filename entry exposes native value and verifies backspace then exact replacement',function()
    a.entering_manual_folder=true;a.entering_manual_str='old'
    local menu=m.menu({width=180,height=77})
    assert(menu.mode=='filename' and menu.filename=='old' and menu.options[1].selection.key=='SELECT')
    m.edit('night',{width=180,height=77})
    assert(a.entering_manual_str=='night' and #inputs==8 and inputs[1]=='STRING_A000')
    a.entering_manual_folder=false
end)
test('overwrite phase has explicit native yes and cancel controls',function()
    a.confirm_manual_overwrite=true
    local menu=m.menu({width=180,height=77})
    assert(menu.mode=='overwrite' and menu.filename=='night' and menu.options[1].native_type=='OVERWRITE')
    assert(menu.options[1].click.x==64 and menu.options[1].click.y==41)
    a.confirm_manual_overwrite=false
end)
test('closed and saving phases do not inspect inactive option pointers',function()
    local saved=a.option;a.option=setmetatable({},{__len=function()error('Inactive native options')end})
    a.open=false;assert(m.menu({})==nil);a.open=true;a.do_manual_save=true
    local menu=m.menu({width=180,height=77});assert(menu.mode=='saving' and #menu.options==0)
    a.do_manual_save=false;a.option=saved
end)
test('unknown build and undeclared confirmation cannot select or edit',function()
    supported=false;assert(m.menu({width=180,height=77}).selection_unavailable)
    assert(not pcall(m.edit,'night',{width=180,height=77}));supported=true
    a.adv_abandon_confirm=true;assert(m.menu({width=180,height=77}).selection_unavailable);a.adv_abandon_confirm=false
end)
test('file evidence uses the native data root and reports failed reads explicitly',function()
    local f=m.file('night');assert(f.available and f.world_exists and f.world_mtime=='123')
    root_ok=false;f=m.file('night');assert(not f.available and f.world_exists==nil);root_ok=true
    modified=-1;assert(not m.file('night').available);modified=123
    for _,name in ipairs({'current','autosave 1','autosave 2','autosave 3','../save'})do assert(not pcall(m.file,name))end
end)
return {passed=#names,tests=names,game_inputs=0}
