-- Condition reader failures must participate in the unit query's coverage.
local source=...
local json=require('json.internal')
local function array()return json:newArray{}end
local result={available=true,complete=false,grapple_count=1,
    unavailable={grapples='Opaque native grapple records'}}
local reads=0
local env=setmetatable({dfhack={units={}}},{__index=_ENV})
local reader=assert(load(source,'unit coverage fixture','t',env))
local helpers={array=array,text=function(v)return v end,health={
    classifications=function()return {available=false,values={isDanger=false},unavailable={isTame='Missing API'}}end,
    combat_condition=function()reads=reads+1;return result end,
    creature_flags=function()return {available=true,complete=true,flags={NOSTUN=false}}end}}
local function run()
    return reader({opponent={unit_id=-1},last_hit={}}, {inventory={}},helpers)
end
local names={}
local function test(name,fn)fn();names[#names+1]=name end
local function coverage(r)
    for _,section in ipairs(r.coverage.sections)do if section.section=='condition' then return section end end
    error('Condition coverage is absent')
end
test('unit query keeps an active hold and makes unreadable details partial',function()
    local r=run()
    assert(reads==1 and r.condition.grapple_count==1 and not r.coverage.complete)
    assert(coverage(r).status=='partial' and r.combat.creature_flags.flags.NOSTUN==false)
    local found=false
    for _,missing in ipairs(r.unavailable)do
        if missing.path=='condition.grapples' then found=true;assert(missing.reason=='Opaque native grapple records')end
    end
    assert(found)
end)
test('condition truncation remains partial even when every field was readable',function()
    result={available=true,complete=false,grapples_omitted=3,grapple_count=19}
    local r=run()
    assert(coverage(r).status=='partial' and r.condition.grapple_count==19)
    local found=false
    for _,missing in ipairs(r.truncated)do
        if missing.path=='condition.grapples' then found=true;assert(missing.omitted==3)end
    end
    assert(found)
end)
test('classification failures and native brief omissions remain explicit',function()
    helpers.brief=true
    local r=run()
    assert(r.classifications.values.isDanger==false and not r.coverage.complete)
    assert(r.coverage.scope=='brief' and #r.coverage.not_queried==2)
    local found=false
    for _,v in ipairs(r.unavailable)do if v.path=='classifications.isTame' then found=true end end
    assert(found)
end)
return {passed=#names,tests=names,game_inputs=0}
