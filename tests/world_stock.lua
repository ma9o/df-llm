-- Isolated material stock fixtures. World records are never edited by the reader.
local source=...
local function vector(values)
    local out={}
    for i,v in ipairs(values)do out[i-1]=v end
    return setmetatable(out,{__len=function()return #values end})
end
local function spec(mat,kind)
    return {mat_type=0,mat_index=mat,tag=kind or 0,getType=function(self)return self.tag end}
end
local function entry(counts,zone,entity)
    return {allotment=0,count=vector(counts),production_zone_index=zone or 10,
        special_controlling_entity_id=entity or -1}
end
local function site(id,entries)
    return {id=id,resource_pile={allotment=entries or {}},global_min_x=0,global_min_y=0}
end
local sites={[0]=site(0,{entry({0,5})}),[1]=site(1,{entry({3,0})})}
local zone={index=10,resource_allotments={[0]=vector({spec(1),spec(2)})}}
local entity={type=0,resource_allotment={resource_allotments={[0]=vector({spec(2)})}}}
local elapsed=0
local env=setmetatable({df={
    global={world={world_data={resource_allotments={zone}}}},
    world_site={find=function(id)return sites[id]end},
    historical_entity={find=function(id)assert(id==7);return entity end},
    historical_entity_type={[0]='SiteGovernment'},
    resource_allotment_specifier_type={[0]='ARMOR_BODY',[1]='CROP'},
    resource_allotment_specifier_armor_bodyst={is_instance=function(_,s)return s.tag==0 end},
    site_realization_building_type={[0]='house',[1]='shop_house'},
    site_realization_building_info_shop_housest={is_instance=function(_,s)return s.tag=='shop' end},
    site_shop_type={[0]='Armorsmith'}},dfhack={
    isWorldLoaded=function()return true end,
    getTickCount=function()return elapsed end,
    matinfo={find=function(name)
        if name=='STEEL' or name=='INORGANIC:STEEL' then
            return {type=0,index=2,getToken=function()return 'INORGANIC:STEEL'end}
        end
    end},translation={translateName=function(name)return name end}}},{__index=_ENV})
local m=assert(load(source,'world-stock-fixture','t',env))({array=function()return {}end,text=function(v)return v end})
local names={}
local function test(name,fn)local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name end
test('unloaded site stock is searchable without a shop or visibility read',function()
    local r=m.read({0,1},'STEEL','epoch')
    assert(r.available and r.material=='INORGANIC:STEEL' and r.world_epoch=='epoch')
    local steel,iron=r.sites[1].stock,r.sites[2].stock
    assert(steel.matched and steel.complete and steel.resource_pile.quantities.ARMOR_BODY==5)
    assert(not steel.sale_records.available and steel.sale_records.reason and #steel.sale_records.shops==0)
    assert(not iron.matched and iron.complete and not next(iron.resource_pile.quantities))
    assert(sites[0].resource_pile.allotment[1].count[1]==5)
end)
test('import counts use the source production zone despite a different controlling entity',function()
    sites[0]=site(0,{entry({0,5},10,999)})
    local r=m.read({0},'STEEL','epoch').sites[1].stock
    assert(r.matched and r.complete and r.resource_pile.quantities.ARMOR_BODY==5)
end)
test('entity production catalog is read only for an absent production zone ID',function()
    sites[0]=site(0,{entry({3},-1,7)})
    local r=m.read({0},'STEEL','epoch').sites[1].stock
    assert(r.matched and r.complete and r.resource_pile.quantities.ARMOR_BODY==3)
    sites[0]=site(0,{entry({3},999,7)})
    r=m.read({0},'STEEL','epoch').sites[1].stock
    assert(not r.complete and not r.matched and r.resource_pile.errors[1].reason:find('Missing production zone'))
end)
test('zero tails never dereference nonexistent materials; positive missing references remain unknown',function()
    sites[0]=site(0,{entry({0,4,0,0})})
    local r=m.read({0},'STEEL','epoch').sites[1].stock
    assert(r.complete and r.resource_pile.quantities.ARMOR_BODY==4)
    sites[0]=site(0,{entry({0,4,7})})
    r=m.read({0},'STEEL','epoch').sites[1].stock
    assert(not r.complete and r.matched and r.resource_pile.quantities.ARMOR_BODY==4)
    assert(r.resource_pile.error_count==1 and r.resource_pile.errors[1].reason:find('no material specifier'))
end)
test('invalid source classes and missing sites cannot become complete negatives',function()
    sites[0]=site(0,{entry({0,5})})
    zone.resource_allotments[0][1].tag=3
    local r=m.read({0,1,55},'STEEL','epoch')
    assert(r.available and not r.sites[1].stock.complete and r.sites[2].stock.complete)
    assert(not r.sites[3].stock.complete and not r.sites[3].stock.resource_pile.available)
    zone.resource_allotments[0][1].tag=0
end)
test('loaded sale records identify the exact shop without adding abstract and sale quantities',function()
    sites[0]=site(0,{entry({0,10})})
    sites[0].realization={buildings={
        setmetatable({type=0},{__index=function()error('Unrelated building read')end}),
        {id=0,type=1,building_info={tag='shop',type=0,name='Steel seller'},
            min_x=0,max_x=0,min_y=0,max_y=0,items={
                setmetatable({flag={for_sale=false}},{__index=function()error('Not for sale')end}),
                {flag={for_sale=true},allotment=0,production_zone_index=10,controlling_civ=999,
                    allotment_idx=1,amount=2}}}}}
    local stock=m.read({0},'STEEL','epoch').sites[1].stock
    local sales=stock.sale_records
    assert(stock.matched and stock.complete and stock.resource_pile.quantities.ARMOR_BODY==10)
    assert(sales.available and sales.quantities.ARMOR_BODY==2 and #sales.shops==1)
    local shop=sales.shops[1]
    assert(shop.id==0 and shop.name=='Steel seller' and shop.type=='Armorsmith' and shop.travel_position.x==0)
end)
test('a material read has a time bound and reports unavailable data without game inputs',function()
    sites[0]=site(0,{entry({0,5})})
    local calls=0
    env.dfhack.getTickCount=function()calls=calls+1;return calls==1 and 0 or 4000 end
    local r=m.read({0},'STEEL','epoch')
    assert(r.available and not r.sites[1].stock.complete and not r.sites[1].stock.matched)
    env.dfhack.getTickCount=function()return elapsed end
end)
test('material validation, zero-site worlds and batch bounds are explicit',function()
    local r=m.read({},'STEEL','epoch')
    assert(r.available and r.material=='INORGANIC:STEEL' and #r.sites==0)
    r=m.read({},'typo','epoch');assert(not r.available and r.reason:find('Unknown native material'))
    local ids={};for i=1,33 do ids[i]=i end
    assert(not m.read(ids,'STEEL','epoch').available)
    assert(not m.read({0,0},'STEEL','epoch').available)
    env.dfhack.isWorldLoaded=function()return false end
    r=m.read({0},'STEEL','epoch');assert(not r.available and r.reason:find('No world is loaded'))
end)
return {passed=#names,tests=names,game_inputs=0}
