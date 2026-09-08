local source=...
local tests={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));tests[#tests+1]=name
end
local function vec(values)
    local v={native=true,n=#values};for i,value in ipairs(values)do v[i-1]=value end
    return setmetatable(v,{__len=function(t)return t.n end})
end
local function native_ipairs(t)
    if not t.native then return ipairs(t)end
    return function(_,i)i=i+1;if i<t.n then return i,t[i]end end,t,-1
end
local p,shop,player,merchant,profiles
local env=setmetatable({ipairs=native_ipairs,df={
    item_type={ARMOR=0,WEAPON=1,[0]='ARMOR',[1]='WEAPON'},
    civzone_type={Home=0,Shop=1,[0]='Home',[1]='Shop'},talk_line_type={[0]='Greet'},
    building_civzonest={is_instance=function(_,b)return b.zone end},
    building={find=function(id)return shop and shop.id==id and shop end}},
    dfhack={isWorldLoaded=function()return true end,
        world={isAdventureMode=function()return true end,getAdventurer=function()return player end},
        buildings={containsTile=function(_,x)return x>=0 end},
        units={isVisible=function(u)return not u.hidden end,isHidden=function(u)return u.hidden or false end},
        items={getReadableDescription=function(i)profiles=profiles+1;return 'item '..i.id end,
            getValue=function()return 0 end,getContainer=function(i)return i.container end}}},{__index=_ENV})
local m=assert(load(source,'barter-fixture','t',env))({array=function()return require('json.internal'):newArray{}end,
    text=function(s)return s end})
local function item(id,kind)
    return {id=id,flags={weight_computed=false},getStackSize=function()return 1 end,
        getType=function()return kind or 0 end,getQuality=function()return 0 end}
end
local function stock(items)
    local flags,amounts={},{}
    for i=1,#items do flags[i]={selected=false,contained=false,whole=0};amounts[i]=0 end
    p.good[0]=vec(items);p.goodflag[0]=vec(flags);p.good_amount[0]=vec(amounts)
end
local function reset()
    profiles=0;player={id=0,pos={x=0,y=0,z=0}};merchant={id=1,pos={x=0,y=0,z=0}}
    shop={id=2,zone=true,type=1,z=0,assigned_units=vec{1}}
    p={open=true,merchant=merchant,your_trader=player,zone={id=3,type=0},personal=false,demand_only=false,
        buildlists=0,talkline=0,entering_amount=0,entering_ask_currency=0,entering_offer_currency=0,
        entering_item_filter={[0]=true,false},scrolling_item={[0]=false,false},item_filter={[0]='',''},
        amount_str='',amount_side=0,amount_index=0,
        currency_trade={[0]=0,0},max_currency={[0]=0,100},good={[0]=vec{},vec{}},
        goodflag={[0]=vec{},vec{}},good_amount={[0]=vec{},vec{}}}
    env.df.global={game={main_interface={adventure={barter=p}}}}
end
local action={unit_id=1,shop_id=2}
test('closed panel pointers are never dereferenced',function()
    reset();env.df.global.game.main_interface.adventure.barter=setmetatable({open=false},
        {__index=function()error('freed pointer')end})
    assert(m.menu()==nil and m.guard()==nil and not m.goods('take',nil,5).open)
end)
test('read-only empty catalog preserves false zero and an object-shaped count map',function()
    reset();local out=m.menu();assert(out.available and not out.editing and not out.personal)
    assert(out.goods.take.count==0 and out.currency.merchant_available==0 and p.zone.id==3 and p.buildlists==0)
    local json=require('json');local encoded=json.encode(out.goods.take.counts,{pretty=false})
    assert(encoded=='{}','Empty catalog must accept object-shaped execution deltas: '..encoded)
end)
test('personal and demand interfaces never read inactive shop pointers',function()
    for _,field in ipairs{'personal','demand_only'}do
        reset();p[field]=true;p.zone=setmetatable({},{__index=function()error('inactive zone pointer')end})
        local out=m.menu();assert(out.available and out.zone==nil)
    end
end)
test('only requested matching goods acquire detailed profiles',function()
    reset();stock{item(0),item(1,1),item(2)}
    local out=m.goods('take','ARMOR',1)
    assert(out.available and out.matched==2 and out.truncated and #out.items==1 and profiles==1)
    assert(out.items[1].id==0 and out.items[1].base_value==0 and out.items[1].weight_unavailable)
    assert(out.items[1].weight_kg==nil and not out.items[1].selected and not p.good[0][0].flags.weight_computed)
    assert(out.items[1].container_id==nil)
    p.good[0][2].container={id=7};p.goodflag[0][2].contained=true
    local boxed=m.goods('take','ARMOR',5)
    assert(boxed.items[2].container_id==7 and boxed.items[2].contained and boxed.items[1].container_id==nil)
end)
test('catalog request changes pending UI only and retains empty filter focus',function()
    reset();m.select_shop(action)
    assert(p.zone==shop and p.buildlists==1 and #p.good[0]==0 and p.max_currency[0]==0)
    assert(p.entering_item_filter[0] and p.item_filter[0]=='')
    assert(m.menu().rebuilding and not m.goods('take',nil,5).available)
end)
test('wrong merchant assignment room visibility and mode refuse before a UI write',function()
    local changes={function()shop.type=0 end,function()shop.assigned_units=vec{}end,
        function()merchant.id=9 end,function()player.pos.x=-1 end,function()merchant.pos.z=1 end,
        function()merchant.hidden=true end,function()p.personal=true end,function()p.demand_only=true end,
        function()p.your_trader={id=9}end}
    for _,change in ipairs(changes)do
        reset();change();assert(not pcall(m.select_shop,action));assert(p.zone.id==3 and p.buildlists==0)
    end
end)
test('offers quantities filters and rebuilding cannot be silently discarded',function()
    local changes={function()p.currency_trade[1]=1 end,function()p.currency_trade[0]=1 end,
        function()p.entering_amount=1 end,function()p.item_filter[0]='iron' end,
        function()stock{item(0)};p.goodflag[0][0].selected=true end,function()p.buildlists=1 end}
    for _,change in ipairs(changes)do
        reset();change();assert(not pcall(m.select_shop,action));assert(p.zone.id==3)
    end
end)
test('inconsistent native vectors are unavailable rather than empty',function()
    reset();p.good[0]=vec{item(0)};local out=m.menu()
    assert(not out.available and out.selection_unavailable and not m.guard().available)
    assert(not pcall(m.select_shop,action) and p.zone.id==3)
end)
test('guards include item identities flags quantities and filter focus',function()
    reset();stock{item(0)};local before=m.guard();p.goodflag[0][0].whole=1
    local after=m.guard();assert(before.available and after.available)
    assert(before.items[1][1][3]==0 and after.items[1][1][3]==1 and after.filter_focus[1])
end)
return {passed=#tests,tests=tests,game_inputs=0}
