--@ module=true
--luacheck: globals factory
local function build(h)
-- Pending adventure trade selections and bounded transfer verification.
-- Provenance: named adventure_interface_barterst good/goodflag/good_amount and
-- currency_trade fields; DFHack internal/caravan/trade.lua edits the equivalent
-- pending fortress selection flags. A guarded character-layer button submits
-- the offer through DF's input handler. No price, ownership or outcome is written.
local M={}
local LIMIT=4096
local function trade_button()
    assert(type(h.ui)=='function' and type(h.click)=='function','Trade button adapter is unavailable')
    local matches={}
    for _,row in ipairs(h.ui().rows)do
        local start=1
        while true do
            local first,last=row.text:find('%f[%a]Trade%f[%A]',start)
            if not first then break end
            matches[#matches+1]={x=utf8.len(row.text:sub(1,first-1))+2,y=row.y}
            start=last+1
        end
    end
    assert(#matches==1,'Expected one visible Trade button; found '..#matches..'; no offer was changed')
    return matches[1]
end
local function integer(v,lo,hi,label)
    assert(type(v)=='number' and v%1==0 and v>=lo and v<=hi,'Invalid '..label)
    return v
end
local function panel(menu)
    assert(menu and menu.kind=='barter' and menu.available,'Native trade state is unavailable')
    local p=df.global.game.main_interface.adventure.barter
    assert(p.open,'Native trade is closed')
    return p
end
local function signature(item)
    local values={item:getType(),item:getSubtype(),item:getMaterial(),item:getMaterialIndex(),
        item:getQuality(),item:getWear(),item:getMakerRace()}
    for _,v in ipairs(values)do assert(type(v)=='number','Native item identity is unavailable')end
    return table.concat(values,':')
end
local function contents(item)
    return dfhack.items.getContainedItems(item)
end
local function inventory(player)
    local held,totals,seen={},{},0
    local function visit(item,depth)
        if held[item.id]then return end
        seen=seen+1;assert(seen<=LIMIT and depth<=16,'Trade inventory exceeds the reading bound')
        local amount=integer(item:getStackSize(),1,2147483647,'native stack size')
        local key=signature(item)
        held[item.id]={amount=amount,signature=key}
        totals[key]=(totals[key] or 0)+amount
        for _,child in ipairs(contents(item))do visit(child,depth+1)end
    end
    assert(#player.inventory<=LIMIT,'Trade inventory exceeds the reading bound')
    for _,entry in ipairs(player.inventory)do visit(entry.item,0)end
    return held,totals
end
function M.read(action,menu)
    local out={available=false,items=h.array(),inventory={}}
    local ok,err=pcall(function()
        local p=panel(menu)
        assert(p.merchant and p.merchant.id==action.unit_id,'The native trade has a different merchant')
        local player=assert(dfhack.world.getAdventurer(),'Local adventurer is unavailable')
        assert(p.your_trader and p.your_trader.id==player.id,'The native trader is not the adventurer')
        local held,totals=inventory(player)
        for _,side in ipairs({'take','give'})do
            assert(type(action[side])=='table' and #action[side]<=32,'Invalid trade item list')
            for _,entry in ipairs(action[side])do
                local id=integer(entry.item_id,0,2147483647,'trade item ID')
                local item=df.item.find(id)
                local row={item_id=id,side=side,present=item~=nil,held=held[id]~=nil}
                if item then
                    row.stack_size=integer(item:getStackSize(),0,2147483647,'native stack size')
                    row.signature=signature(item)
                    out.inventory[row.signature]=totals[row.signature] or 0
                end
                out.items[#out.items+1]=row
            end
        end
        -- Keep totals for original signatures even when a stack was merged/deleted.
        assert(not action.signatures or #action.signatures<=64,'Trade signatures exceed the reading bound')
        for _,key in ipairs(action.signatures or {})do
            assert(type(key)=='string' and #key<=200,'Invalid trade item signature')
            out.inventory[key]=totals[key] or 0
        end
        out.currency={player=menu.currency.player_available,merchant=menu.currency.merchant_available}
        out.counter_offer={offer_currency=menu.currency.offer,request_currency=menu.currency.request}
        out.unit_id=menu.unit_id;out.trader_id=menu.trader_id;out.talkline=menu.talkline
        local reply={}
        for i,line in ipairs(p.big_announce.text)do
            if i>=8 then out.reply_truncated=true;break end
            local value=h.text(line)
            local cut=utf8.offset(value,501)
            if cut then out.reply_truncated=true;value=value:sub(1,cut-1)end
            reply[#reply+1]=value
        end
        out.reply=table.concat(reply,' ')
        if not action.verify then
            local valid,why=pcall(M.plan,action)
            if not valid then out.selection_unavailable=tostring(why):sub(1,240)end
        end
        out.available=true
    end)
    if not ok then out.reason=tostring(err):sub(1,240)end
    return out
end
function M.plan(action)
    local menu=h.barter.menu()
    local p=panel(menu)
    assert(not menu.rebuilding and not menu.editing,'The native trade is rebuilding or editing a quantity/filter')
    assert(not menu.demand_only,'This action submits a trade, not a demand')
    assert(menu.unit_id==action.unit_id,'The native trade has a different merchant')
    assert(p.your_trader==dfhack.world.getAdventurer(),'The native trader is not the adventurer')
    local plan={sides={},currency={}}
    local player=p.your_trader
    local roles={}
    for _,entry in ipairs(player.inventory)do roles[entry.item.id]=entry.mode end
    local selected={}
    for index,side in ipairs({'take','give'})do
        local wanted={};local total=0
        assert(type(action[side])=='table' and #action[side]<=32,'Invalid trade item list')
        for _,entry in ipairs(action[side])do
            local id=integer(entry.item_id,0,2147483647,'trade item ID')
            assert(not selected[id],'Trade item IDs must be distinct')
            selected[id]=true;wanted[id]=integer(entry.amount,1,2147483647,'trade quantity');total=total+1
        end
        local native=index-1
        local goods,flags,amounts=p.good[native],p.goodflag[native],p.good_amount[native]
        assert(#goods<=LIMIT and #goods==#flags and #goods==#amounts,'Native trade vectors are unavailable or truncated')
        local rows={};plan.sides[native]=rows
        for i,item in ipairs(goods)do
            local amount=wanted[item.id]
            assert(type(flags[i].selected)=='boolean' and type(flags[i].contained)=='boolean','Native trade flags are unavailable')
            if amount then
                assert(not flags[i].contained and not dfhack.items.getContainer(item),
                    'Contained-item trade scope is unsupported; no selection was made')
                if side=='give' then
                    assert(roles[item.id]==df.inv_item_role_type.Hauled
                        or roles[item.id]==df.inv_item_role_type.Weapon,
                        'Sale item must be held separately; remove or take it from its container first')
                end
                assert(#contents(item)==0,'Trading a nonempty container includes its contents; this action only supports items without contents')
                assert(item:getType()~=df.item_type.COINS,'Use native currency amounts instead of selecting coin items')
                assert(amount<=item:getStackSize(),'Requested quantity exceeds the native stack')
                rows[#rows+1]={index=i,amount=amount}
                wanted[item.id]=nil;total=total-1
            end
        end
        assert(total==0,'A requested item is absent from its native trade side')
    end
    plan.currency[0]=integer(action.request_currency or 0,0,2147483647,'requested currency')
    plan.currency[1]=integer(action.offer_currency or 0,0,2147483647,'offered currency')
    assert(plan.currency[0]<=menu.currency.merchant_available and plan.currency[1]<=menu.currency.player_available,
        'Requested currency exceeds the native amount-entry bounds')
    -- Price acceptance remains entirely with the game's trade handler.
    assert(next(selected) or plan.currency[0]~=0 or plan.currency[1]~=0,'The requested offer is empty')
    assert(next(selected) or plan.currency[0]~=plan.currency[1],'A currency-only trade requires a verifiable balance change')
    plan.button=trade_button() -- Resolve before any pending offer writes.
    return p,plan
end
function M.submit(action)
    local p,plan=M.plan(action) -- All validation precedes the first pending UI write.
    for side=0,1 do
        for i,flag in ipairs(p.goodflag[side])do flag.selected=false;p.good_amount[side][i]=0 end
        for _,row in ipairs(plan.sides[side])do
            p.goodflag[side][row.index].selected=true
            p.good_amount[side][row.index]=row.amount
        end
        p.currency_trade[side]=plan.currency[side]
    end
    h.click(plan.button.x,plan.button.y)
    return {adapter='native_barter_offer_and_character_button',submitted=true}
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
