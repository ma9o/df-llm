local source=...
local env=setmetatable({df={matter_state={[0]='Solid'}},dfhack={
    items={getCapacity=function(i)return i.capacity end},
    matinfo={decode=function()return {getToken=function()return 'WATER' end}end}}},{__index=_ENV})
local m=assert(load(source,'item-storage-fixture','t',env))({array=function()return {}end})
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
env.df.adventure_option_drop_itemst={is_instance=function(_,o)return o.tag=='drop' end}
env.dfhack.items.getContainer=function(item)return item.container end
local function drop(liquid,depth)
    return {tag='drop',depth=depth,item={isLiquid=function()return liquid end,container={id=0}}}
end
test('dropping a contained liquid is explicitly whole-container emptying',function()
    local out=m.option(drop(true,1),'DROP_ITEM',true)
    assert(out.operation=='empty_container' and out.container_id==0 and not out.details_unavailable)
    assert(m.option(drop(false,1),'DROP_ITEM',true).operation=='drop_item')
    assert(m.option(drop(true,0),'DROP_ITEM',true).operation=='drop_item')
end)
test('unknown liquid drop semantics cannot be presented as an ordinary drop',function()
    local out=m.option(drop(true,1),'DROP_ITEM',false)
    assert(out.details_unavailable and not out.operation)
    local o=drop(true,1);o.item.container=nil;out=m.option(o,'DROP_ITEM',true)
    assert(out.details_unavailable and not out.operation)
    o=drop(nil,1);out=m.option(o,'DROP_ITEM',true)
    assert(out.details_unavailable and not out.operation)
end)
test('non-drop menus never read a drop payload',function()
    local o=setmetatable({},{__index=function()error('inactive drop payload')end})
    assert(not next(m.option(o,'OTHER',true)))
end)
test('zero capacity and absent coatings are known, without inventing a container',function()
    local r=m.storage({capacity=0})
    assert(r.capacity_volume_raw==0 and #r.contaminants==0 and not r.capacity_unavailable)
end)
test('unknown capacity and coating reads remain unavailable instead of empty',function()
    local r=m.storage(setmetatable({capacity=false},{__index=function()error('unreadable item field')end}))
    assert(r.capacity_unavailable and r.capacity_volume_raw==nil and r.contaminants_unavailable and r.contaminants==nil)
end)
test('coatings preserve false zero native material and explicit bounds',function()
    local c={base={mat_type=6,mat_index=-1,mat_state=0,size=0,temperature={whole=0,fraction=0},
        base_flags={evaporates=false}},body_part_id=-1,flags={external=false}}
    local list={};for i=1,129 do list[i]=c end
    local r=m.storage({capacity=180,contaminants=list})
    assert(r.capacity_volume_raw==180 and #r.contaminants==128 and r.contaminants_truncated and r.contaminants_total==129)
    assert(r.contaminants[1].material=='WATER' and r.contaminants[1].external==false and r.contaminants[1].size==0)
end)
return {passed=#names,tests=names,game_inputs=0}
