local source=...
local names={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name end
local player={id=1,inventory={}}
local objects={}
local function item(id,amount)
    local obj={id=id,amount=amount,children={}}
    function obj:getStackSize()return self.amount end
    function obj.getType()return 1 end
    function obj.getSubtype()return -1 end
    function obj.getMaterial()return 0 end
    function obj.getMaterialIndex()return 2 end
    function obj.getQuality()return 0 end
    function obj.getWear()return 0 end
    function obj.getMakerRace()return -1 end
    objects[id]=obj;return obj
end
local goods=item(10,5)
local p={open=true,merchant={id=2},your_trader=player,
    good={[0]={[0]=goods},[1]={}},goodflag={[0]={[0]={selected=false,contained=false}},[1]={}},
    good_amount={[0]={[0]=0},[1]={}},currency_trade={[0]=0,[1]=0},big_announce={text={}}}
local function vector(v)
    return setmetatable(v,{__len=function(t)local n=0;while rawget(t,n)~=nil do n=n+1 end;return n end,
        __ipairs=function(t)local n=-1;return function()n=n+1;if n<#t then return n,t[n]end end end})
end
for _,key in ipairs({'good','goodflag','good_amount'})do for side=0,1 do p[key][side]=vector(p[key][side])end end
local menu={kind='barter',available=true,unit_id=2,trader_id=1,currency={player_available=100,merchant_available=30},talkline='Greet'}
local inputs=0
local ui={rows={{y=25,text='                   Trade       Show'}}}
local env=setmetatable({df={global={game={main_interface={adventure={barter=p}}}},
    item={find=function(id)return objects[id]end},item_type={COINS=2},inv_item_role_type={Hauled=0,Weapon=1,Worn=2}},
    dfhack={world={getAdventurer=function()return player end},items={
        getContainedItems=function(i)return i.children end,getContainer=function(i)return i.container end}}}, {__index=_ENV})
local m=assert(load(source,'exchange-fixture','t',env))({array=function()return {}end,text=function(s)return s end,
    barter={menu=function()return menu end},ui=function()return ui end,click=function(x,y)
        inputs=inputs+1
        assert(x==21 and y==25)
        assert(p.goodflag[0][0].selected and p.good_amount[0][0]==2 and p.currency_trade[1]==5)
    end})
local action={unit_id=2,take={{item_id=10,amount=2}},give={},offer_currency=5}
test('trade preview reads do not change pending selections or native ownership',function()
    local out=m.read(action,menu)
    assert(out.available and not out.selection_unavailable and out.items[1].stack_size==5)
    assert(out.inventory['1:-1:0:2:0:0:-1']==0 and not out.items[1].held)
    assert(inputs==0 and not p.goodflag[0][0].selected and p.good_amount[0][0]==0)
end)
test('a complete offer is validated before any pending write and submitted once through an injected fixture handler',function()
    m.submit(action)
    assert(inputs==1 and goods.amount==5 and #player.inventory==0)
end)
test('missing adapter cannot change an offer or send an input',function()
    local unavailable=assert(load(source,'exchange-unavailable','t',env))({array=function()return {}end,
        text=function(s)return s end,barter={menu=function()return menu end}})
    local before=p.good_amount[0][0]
    local out=unavailable.read(action,menu)
    assert(out.available and out.selection_unavailable:find('adapter is unavailable',1,true))
    assert(not pcall(unavailable.submit,action))
    assert(p.good_amount[0][0]==before and inputs==1)
end)
test('missing or ambiguous Trade text rejects before replacing an offer',function()
    local old=ui.rows
    for _,rows in ipairs({{},{{y=4,text='Trade  Trade'}},{{y=4,text='Trader'}}})do
        ui.rows=rows
        assert(not pcall(m.submit,action))
        assert(p.good_amount[0][0]==2 and p.currency_trade[1]==5 and inputs==1)
    end
    ui.rows={{y=7,text='é    Trade'}}
    local _,plan=m.plan(action)
    assert(plan.button.x==7 and plan.button.y==7) -- Unicode cells, not byte offsets.
    ui.rows=old
end)
test('equipped sale items are refused before pending selections change',function()
    local sale=item(20,1)
    player.inventory={{item=sale,mode=2}}
    p.good[1][0]=sale;p.goodflag[1][0]={selected=false,contained=false};p.good_amount[1][0]=0
    local offer={unit_id=2,take={},give={{item_id=20,amount=1}},request_currency=5}
    assert(not pcall(m.submit,offer) and inputs==1 and not p.goodflag[1][0].selected)
    player.inventory[1].mode=0
    assert(pcall(m.plan,offer))
    player.inventory[1].mode=1
    assert(pcall(m.plan,offer))
    player.inventory={};p.good[1][0]=nil;p.goodflag[1][0]=nil;p.good_amount[1][0]=nil
end)
test('native quantity limits and unknown IDs cannot partially replace the current offer',function()
    for _,entry in ipairs({{item_id=10,amount=6},{item_id=99,amount=1}})do
        assert(not pcall(m.submit,{unit_id=2,take={entry},give={},offer_currency=5}))
        assert(p.goodflag[0][0].selected and p.good_amount[0][0]==2 and inputs==1)
    end
    assert(not pcall(m.submit,{unit_id=2,take={{item_id=10,amount=1}},give={},offer_currency=101}))
end)
test('broader container selection is rejected before an input',function()
    goods.children={item(11,1)}
    local out=m.read(action,menu)
    assert(out.available and out.selection_unavailable:find('includes its contents',1,true))
    assert(not pcall(m.submit,action) and inputs==1)
    goods.children={};goods.container={id=9}
    assert(not pcall(m.submit,action) and inputs==1)
    goods.container=nil;p.goodflag[0][0].contained=true
    assert(not pcall(m.submit,action));p.goodflag[0][0].contained=false
end)
test('closed trade pointers are never read',function()
    local old=env.df.global.game.main_interface.adventure.barter
    env.df.global.game.main_interface.adventure.barter=setmetatable({open=false},{__index=function()error('inactive pointer read')end})
    local out=m.read(action,menu)
    assert(not out.available and out.reason:find('closed',1,true))
    env.df.global.game.main_interface.adventure.barter=old
end)
test('post-submission reads retain original signatures after the source stack disappears',function()
    local received=item(12,2);player.inventory={{item=received}}
    objects[10]=nil
    local out=m.read({unit_id=2,take=action.take,give={},verify=true,signatures={'1:-1:0:2:0:0:-1'}},menu)
    assert(out.available and not out.items[1].present and out.inventory['1:-1:0:2:0:0:-1']==2)
    assert(inputs==1)
end)
return {passed=#names,tests=names,game_inputs=0}
