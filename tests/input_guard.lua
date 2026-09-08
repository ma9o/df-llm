-- Exercise the actual guard encoder using plain fixtures, never game state.
local source=...
local guard=assert(load(source))()
local json=require('json')
local function copy(v)return json.decode(json.encode(v))end
local s={screen='viewscreen_dungeonmodest',focus={'dungeonmode/Inventory'},world_frame=42,
    action_serial=7,position={x=1,y=2,z=3},open_panels={'inventory'},ready_for_input=true}
local ui={width=180,height=77,rows={{y=0,text='A blinking tooltip'}}}
local n={complete=true,menu={kind='inventory',context=3,context_item_id=4,scroll=0,
    options={{id='native:1',item_id=1},{id='native:2',item_id=2}}},
    character={blood=1000,wounds=0,on_ground=false,inventory={{id=5,stack=2}}}}
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('known native state ignores incidental rendered text',function()
    local changed=copy(ui);changed.rows[1].text='Other tooltip'
    assert(guard(s,ui,n)==guard(s,changed,n))
end)
test('native guard is independent of table insertion order',function()
    local changed={};changed.menu=n.menu;changed.character=n.character;changed.complete=true
    assert(guard(s,ui,n)==guard(s,ui,changed))
end)
test('option reorder and replacement invalidate a guard without advancing time',function()
    local changed=copy(n);changed.menu.options[1],changed.menu.options[2]=changed.menu.options[2],changed.menu.options[1]
    assert(guard(s,ui,n)~=guard(s,ui,changed))
    changed=copy(n);changed.menu.options[1].item_id=99
    assert(guard(s,ui,n)~=guard(s,ui,changed))
end)
test('menu context, target, scroll and filter changes invalidate a guard',function()
    for _,pair in ipairs({{'context',8},{'context_item_id',44},{'scroll',1},{'filter','new'}}) do
        local changed=copy(n);changed.menu[pair[1]]=pair[2]
        assert(guard(s,ui,n)~=guard(s,ui,changed))
    end
end)
test('health, inventory, false and zero remain guarded',function()
    local changed=copy(n);changed.character.blood=999
    assert(guard(s,ui,n)~=guard(s,ui,changed))
    changed=copy(n);changed.character.inventory[1].stack=1
    assert(guard(s,ui,n)~=guard(s,ui,changed))
    changed=copy(n);changed.character.wounds=nil
    assert(guard(s,ui,n)~=guard(s,ui,changed))
    changed=copy(n);changed.character.on_ground=nil
    assert(guard(s,ui,n)~=guard(s,ui,changed))
end)
test('undecoded interfaces retain rendered text guard',function()
    local changed=copy(ui);changed.rows[1].text='Undelegated choice changed'
    local fallback=copy(n);fallback.complete=false
    assert(guard(s,ui,fallback)~=guard(s,changed,fallback))
end)
test('modal and coordinate frame changes invalidate native guard',function()
    local changed=copy(s);changed.modal={kind='action_prompt'}
    assert(guard(s,ui,n)~=guard(changed,ui,n))
    changed=copy(s);changed.map_origin={x=10,y=20,z=0}
    assert(guard(s,ui,n)~=guard(changed,ui,n))
end)
test('native help content stays guarded while unrelated background text can change',function()
    local help=copy(s);help.modal={kind='help',title='Travel',text={'Instructions'},button='Okay'}
    local background=copy(ui);background.rows[1].text='Blink'
    assert(guard(help,ui,n)==guard(help,background,n))
    local changed=copy(help);changed.modal.text[1]='Different instructions'
    assert(guard(help,ui,n)~=guard(changed,ui,n))
end)
test('input serial is excluded only from effect identity',function()
    local changed=copy(s);changed.action_serial=8
    assert(guard(s,ui,n)~=guard(changed,ui,n))
    assert(guard(s,ui,n,true)==guard(changed,ui,n,true))
end)
test('travel map toggles change input and effect identity without simulation time',function()
    local before=copy(s);before.open_panels={}
    before.travel={active=true,position={x=1,y=2,z=0},map_view={available=true,open=false,mode='MapNone'}}
    local after=copy(before);after.travel.map_view={available=true,open=true,mode='MapSite',close_key='A_TRAVEL_MAP'}
    assert(guard(before,ui,n)~=guard(after,ui,n))
    assert(guard(before,ui,n,true)~=guard(after,ui,n,true))
    local changed=copy(ui);changed.rows[1].text='Repainted map'
    assert(guard(after,ui,n)==guard(after,changed,n))
end)
test('native help reflow preserves semantic identity without mutating the observation',function()
    local help=copy(s);help.modal={kind='help',title='Travel',button='Okay',
        text={'This is travel mode.  Here you can travel great distances.'}}
    local reflow=copy(help);reflow.modal.text={'This is travel mode.','','Here you can travel',
        'great distances.'}
    assert(guard(help,ui,n)==guard(reflow,ui,n))
    assert(type(reflow.modal.text)=='table' and #reflow.modal.text==4)
    reflow.modal.text[4]='short distances.'
    assert(guard(help,ui,n)~=guard(reflow,ui,n))
end)
return {passed=#names,tests=names,game_inputs=0}
