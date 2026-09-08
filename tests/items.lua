local source=...
local env=setmetatable({df={matter_state={[0]='Solid'}},dfhack={
    items={getCapacity=function(i)return i.capacity end},
    matinfo={decode=function()return {getToken=function()return 'WATER' end}end}}},{__index=_ENV})
local m=assert(load(source,'item-storage-fixture','t',env))({array=function()return {}end})
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
env.df.building_actual={is_instance=function(_,b)return b.actual==true end}
env.df.building_item_role_type={[0]='TEMP',[1]='TEMP_PRINTHIDDEN',[2]='PERM'}
env.df.item_type={[0]='ARMOR',[1]='WEAPON',ARMOR=0,WEAPON=1}
env.dfhack.maps={isTileVisible=function(x)return x>=0 end}
env.dfhack.items.getPosition=function(i)return i.pos.x,i.pos.y,i.pos.z end
env.dfhack.items.getHolderBuilding=function(i)return i.holder end
local function stored(id,kind,hidden)
    return {id=id,flags={hidden=hidden or false,on_ground=false,in_building=false},
        pos={x=0,y=1,z=2},getType=function()return kind or 0 end}
end
local function furniture(records)
    return {id=0,actual=true,centerx=0,centery=1,z=2,contained_items=records}
end
test('furniture TEMP records expose goods with neither ground nor building flags',function()
    local item=stored(0)
    local b=furniture({{use_mode=2,item=stored(9)},{use_mode=0,item=item}});item.holder=b
    local r=m.building_contents(b,10)
    assert(r.available and r.item_count==1 and r.omitted_permanent==1 and not r.truncated)
    assert(r.entries[1].id==0 and r.entries[1].location.kind=='building')
    local loc=m.building_location(item)
    assert(loc and loc.building_id==0 and loc.root_item_id==0 and loc.position.x==0)
end)
test('native furniture filtering retains whole-stock counts and explicit result bounds',function()
    local b=furniture({{use_mode=0,item=stored(0)},{use_mode=0,item=stored(1,1)},
        {use_mode=0,item=stored(2)}})
    local r=m.building_contents(b,1,'ARMOR')
    assert(r.available and r.matched==2 and #r.entries==1 and r.truncated)
    assert(r.item_count==3 and r.counts.WEAPON==1 and r.counts.ARMOR==2)
    r=m.building_contents(b,0)
    assert(r.available and r.item_count==3 and #r.entries==0)
end)
test('installed and print-hidden payloads stay unread; hidden goods remain omitted',function()
    local bad=setmetatable({},{__index=function()error('Must not read this item')end})
    local b=furniture({{use_mode=2,item=bad},{use_mode=1,item=bad},
        {use_mode=0,item=stored(0,0,true)}})
    local r=m.building_contents(b,10)
    assert(r.available and r.item_count==0 and r.omitted_hidden==2 and r.omitted_permanent==1)
end)
test('invisible furniture and unrelated native classes are unavailable without traversal',function()
    local b=setmetatable({actual=false},{__index=function()error('inactive class payload')end})
    local r=m.building_contents(b,10);assert(not r.available and r.reason)
    b=setmetatable({actual=true,centerx=-1,centery=0,z=0},{__index=function()error('hidden storage read')end})
    r=m.building_contents(b,10);assert(not r.available and r.reason)
end)
test('missing native storage and unknown roles are never reported as an empty success',function()
    for _,b in ipairs({furniture(nil),furniture({{use_mode=99}}),furniture({{use_mode=0}})})do
        local r=m.building_contents(b,10);assert(not r.available and r.reason)
    end
    local r=m.building_contents(furniture({}),10)
    assert(r.available and r.item_count==0 and r.truncated==false)
end)
test('furniture scanning has a bound independent of emitted matches',function()
    local records={};for i=1,4097 do records[i]={use_mode=0,item=stored(i)}end
    local r=m.building_contents(furniture(records),10,'WEAPON')
    assert(r.available and r.scanned==4096 and r.scan_truncated and r.truncated and r.matched==0)
end)
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
test('catalog reads retain nested identities and facts without reading omitted definitions',function()
    local heavy=0
    local function copy(v)
        if type(v)~='table' then return v end
        local out={};for k,x in pairs(v)do out[k]=copy(x)end;return out
    end
    local reader=assert(load(source,'catalog-fixture','t',env))({array=function()return {}end,
        text=function(v)return v end,copy=copy,optional=function(fn)local ok,v=pcall(fn);if ok then return v end end})
    env.df.item_type.WEAPON=1;env.df.job_skill={[0]='SWORD'}
    env.dfhack.matinfo.decode=function()return {type=0,index=0,getToken=function()return 'IRON' end,
        toString=function()heavy=heavy+1;return 'iron' end}end
    env.dfhack.items.getReadableDescription=function(i)return 'item '..i.id end
    env.dfhack.items.getContainedItems=function(i)return i.children or {}end
    local armor_flags={}
    env.df.armor_general_flags={SHAPED=0};env.df.clothing_layer_type={[0]='UNDER'}
    env.dfhack.items.getSubtypeDef=function()return {id='SWORD',name='sword',skill_melee=0,
        minimum_size=0,two_handed=0,props={coverage=0,layer=0,layer_size=0,layer_permit=0,flags=armor_flags},attacks={}}end
    local function item(id)
        return setmetatable({id=id,capacity=0,contaminants={},flags={weight_computed=false,hidden=false},
            weight={whole=0,fraction=0},getQuality=function()return 0 end,getWear=function()return 0 end,
            getType=function()return 1 end,getSubtype=function()return 0 end,getStackSize=function()return 1 end,
            getMakerRace=function()return -1 end,getVolume=function()heavy=heavy+1;return 0 end},
            {__index=function(_,k)if k=='temperature' then heavy=heavy+1;return {whole=0,fraction=0}end end})
    end
    local root=item(1);root.capacity=10;root.children={item(2)}
    local location={kind='ground',position={x=0,y=0,z=0},root_item_id=1}
    local out=reader.info(root,0,{remaining=10,catalog=true},location)
    assert(heavy==0 and out.id==1 and out.contents[1].id==2)
    assert(out.contents[1].location.container_id==1 and out.contents[1].location.root_item_id==1)
    assert(out.weight_computed==false and out.wear==0 and out.material_ref.index==0 and out.armor.coverage==0)
    assert(not out.weapon and not out.definition and not out.temperature)
    assert(out.armor.shaped==nil and out.armor.shaped_unavailable and out.armor.layer_name=='UNDER')
    for _,shaped in ipairs({false,true})do
        armor_flags[0]=shaped
        local value=reader.info(root,0,{remaining=10,catalog=true},location)
        assert(value.armor.shaped==shaped and not value.armor.shaped_unavailable)
    end
    local full=reader.info(root,0,{remaining=10},location)
    assert(heavy>0 and full.weapon and full.definition and full.temperature.whole==0)
    local bounded=reader.info(root,0,{remaining=1,catalog=true},location)
    assert(bounded.contents_truncated and bounded.contents_total==1)
end)
return {passed=#names,tests=names,game_inputs=0}
