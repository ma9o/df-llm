--@ module=true
--luacheck: globals factory
local function build(h)
-- Adventure trade context adapter. Only the pending UI catalog is selected;
-- DF builds its goods/currency lists and performs all pricing and transfers.
-- Named fields: adventure_interface_barterst.zone and its buildlists request.
-- Like DFHack's caravan UI, this edits a pending trade interface, not ownership.
local M={}
local LIMIT=4096
local function panel()
    if not dfhack.isWorldLoaded() or not dfhack.world.isAdventureMode() then return end
    local p=df.global.game.main_interface.adventure.barter
    if p.open then return p end -- Closed-panel pointers can have been freed.
end
local function integer(v,lo,hi,label)
    assert(type(v)=='number' and v%1==0 and v>=lo and v<=hi,'Invalid '..label)
    return v
end
local function rows(p,side,fn)
    local goods,flags,amounts=p.good[side],p.goodflag[side],p.good_amount[side]
    assert(#goods<=LIMIT,'Trade goods exceed the 4096-entry reading limit')
    assert(#goods==#flags and #goods==#amounts,'Native trade vectors differ in length')
    for i,item in ipairs(goods)do
        assert(item,'Missing native trade item')
        local f=flags[i]
        assert(type(f.selected)=='boolean' and type(f.contained)=='boolean','Unknown trade flags')
        fn(item,f,integer(amounts[i],0,item:getStackSize(),'trade amount'),i)
    end
end
local function editing(p)
    return p.entering_amount~=0 or p.entering_ask_currency~=0 or p.entering_offer_currency~=0
        -- DF can focus an empty filter by default. Rebuilding retains that
        -- focus; it is not an unfinished quantity/currency edit.
        or p.item_filter[0]~='' or p.item_filter[1]~=''
        or p.scrolling_item[0] or p.scrolling_item[1]
end
local function assigned(shop,merchant)
    assert(#shop.assigned_units<=LIMIT,'Shop assignments exceed the reading limit')
    for _,id in ipairs(shop.assigned_units)do if id==merchant.id then return true end end
    return false
end
local function inside(shop,u)
    return u.pos.z==shop.z and dfhack.buildings.containsTile(shop,u.pos.x,u.pos.y)
end
function M.menu()
    local p=panel();if not p then return end
    local out={kind='barter',open=true,available=false,options=h.array()}
    local ok,err=pcall(function()
        out.unit_id=assert(p.merchant,'Missing trade merchant').id
        out.trader_id=assert(p.your_trader,'Missing player trader').id
        out.personal=p.personal;out.demand_only=p.demand_only
        if not p.personal and not p.demand_only then
            out.zone=p.zone and {id=p.zone.id,type=df.civzone_type[p.zone.type]} or nil
        end
        out.rebuilding=p.buildlists~=0
        out.editing=editing(p)
        out.talkline=df.talk_line_type[p.talkline]
        out.currency={request=p.currency_trade[0],offer=p.currency_trade[1],
            merchant_available=p.max_currency[0],player_available=p.max_currency[1]}
        for k,v in pairs(out.currency)do integer(v,0,2147483647,'currency.'..k)end
        out.goods={};out.draft={take=h.array(),give=h.array()}
        for side,name in ipairs({'take','give'})do
            -- Explicit object identity matters: DFHack encodes an untyped empty
            -- table as [], which cannot receive an object-shaped wire delta.
            local counts=require('json.internal'):newObject{};local count=0
            rows(p,side-1,function(item,f,amount)
                local kind=assert(df.item_type[item:getType()],'Unknown native item type')
                counts[kind]=(counts[kind] or 0)+1;count=count+1
                if f.selected then out.draft[name][#out.draft[name]+1]={id=item.id,amount=amount}end
            end)
            out.goods[name]={count=count,counts=counts}
        end
        out.available=true
    end)
    if not ok then out.selection_unavailable=tostring(err):sub(1,240)end
    return out
end
function M.guard()
    local p=panel();if not p then return end
    local out={available=false}
    local ok,err=pcall(function()
        out.items=h.array()
        for side=0,1 do
            local list=h.array();out.items[#out.items+1]=list
            rows(p,side,function(item,f,amount)
                list[#list+1]={item.id,item:getStackSize(),f.whole,amount}
            end)
        end
        out.filters={p.item_filter[0],p.item_filter[1]}
        out.filter_focus={p.entering_item_filter[0],p.entering_item_filter[1]}
        out.amount={p.amount_str,p.amount_side,p.amount_index}
        out.available=true
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
function M.validate_shop(action)
    integer(action.unit_id,0,2147483647,'merchant ID')
    integer(action.shop_id,0,2147483647,'shop zone ID')
    local p=assert(panel(),'No native trade is open')
    local current=M.menu()
    assert(current.available,current.selection_unavailable)
    assert(not current.personal and not current.demand_only,'An ordinary shop trade is required')
    assert(p.merchant.id==action.unit_id,'The native trade has a different merchant')
    local player=assert(dfhack.world.getAdventurer(),'No local adventurer')
    assert(p.your_trader.id==player.id,'The native trader is not the adventurer')
    assert(not current.rebuilding and not current.editing,'Finish the active trade edit first')
    assert(current.currency.offer==0 and current.currency.request==0
        and #current.draft.take==0 and #current.draft.give==0,'A pending offer must not be discarded')
    assert(p.item_filter[0]=='' and p.item_filter[1]=='','Clear the current trade filters first')
    local shop=df.building.find(action.shop_id)
    assert(shop and df.building_civzonest:is_instance(shop) and shop.type==df.civzone_type.Shop,
        'The requested building is not a loaded Shop zone')
    assert(assigned(shop,p.merchant),'The merchant is not assigned to the requested shop')
    assert(dfhack.units.isVisible(p.merchant) and not dfhack.units.isHidden(p.merchant),
        'The merchant is not visible')
    assert(inside(shop,player) and inside(shop,p.merchant),'Both traders must be inside the requested shop')
    return p,shop
end
function M.select_shop(action)
    local p,shop=M.validate_shop(action)
    local before=p.zone and p.zone.id
    p.zone=shop
    p.buildlists=1 -- Pending native UI work. The game rebuilds on its next render.
    return {before_zone=before,requested_shop_id=shop.id,adapter='native_barter_catalog'}
end
function M.goods(side,item_type,limit)
    assert(side=='take' or side=='give','side must be take or give')
    integer(limit,1,500,'limit')
    local wanted=item_type and df.item_type[item_type]
    assert(item_type==nil or type(wanted)=='number','Unknown native item type')
    local out=M.menu() or {open=false,available=false,reason='No native trade is open'}
    out.side=side;out.items=h.array()
    out.kind=nil;out.options=nil;out.trader_id=nil;out.talkline=nil
    out.total=out.goods and out.goods[side].count
    out.goods=nil
    if out.draft and #out.draft.take==0 and #out.draft.give==0 then out.draft=nil end
    if not out.available then return out end
    if out.rebuilding then out.available=false;out.reason='The native catalog is rebuilding';return out end
    local p=assert(panel());out.matched=0
    rows(p,side=='take' and 0 or 1,function(item,f,amount)
        if wanted==nil or item:getType()==wanted then
            out.matched=out.matched+1
            if #out.items<limit then
                local entry={id=item.id,description=h.text(dfhack.items.getReadableDescription(item)),
                    type=df.item_type[item:getType()],stack_size=item:getStackSize(),
                    selected=f.selected,contained=f.contained,amount=amount,
                    quality=item:getQuality(),base_value=dfhack.items.getValue(item)}
                if item.flags.weight_computed then entry.weight_kg=item.weight.whole+item.weight.fraction/1000000
                else entry.weight_unavailable='Native weight is not computed' end
                out.items[#out.items+1]=entry
            end
        end
    end)
    out.truncated=out.matched>#out.items
    out.value_note='base_value is DFHack item value, not a negotiated price'
    return out
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
