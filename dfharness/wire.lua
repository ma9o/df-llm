--@ module=true
--luacheck: globals factory
local function build()
-- Lossless execution transport. Snapshots contain JSON values, never DF pointers.
local M={}
local json=require('json')
local internal=require('json.internal')
dfhack.df_llm_json_null=dfhack.df_llm_json_null or {}
M.null=dfhack.df_llm_json_null
local function object()return internal:newObject{} end
local function array()return internal:newArray{} end
local array_meta=getmetatable(array())
local function is_array(v)
    return type(v)=='table' and (getmetatable(v)==array_meta or rawget(v,1)~=nil)
end
function M.encode(value) return json.encode(value,{pretty=false,null=M.null}) end
function M.intent(request)
    if type(request)=='string' then
        request=internal:new{strictTypes=true}:decode(request,nil,{null=M.null})
    end
    return M.encode({action=request.action,execution=request.execution,expect=request.expect})
end
function M.clone(value)
    if type(value)~='table' or value==M.null then return value end
    local out=setmetatable({},getmetatable(value))
    for k,v in pairs(value)do out[k]=M.clone(v) end
    return out
end
function M.delta(before,after)
    if before==after then return object() end
    if type(before)~=type(after) or type(after)~='table' or before==M.null or after==M.null
        or is_array(before)~=is_array(after) then return {set=M.clone(after)} end
    local out=object()
    if is_array(after) then
        local entries=object();local count=0
        for i,v in ipairs(after)do
            local d=i<=#before and M.delta(before[i],v) or {set=M.clone(v)}
            if next(d) then entries[tostring(i-1)]=d;count=count+1 end
        end
        if #after>0 and count==#after then return {set=M.clone(after)} end
        if count>0 then out.entries=entries end
        if #before~=#after then out.length=#after end
    else
        local fields=object();local removed=array()
        for k,v in pairs(after)do
            local d=before[k]~=nil and M.delta(before[k],v) or {set=M.clone(v)}
            if next(d) then fields[k]=d end
        end
        for k in pairs(before)do if after[k]==nil then removed[#removed+1]=k end end
        if next(fields)then out.fields=fields end
        if #removed>0 then table.sort(removed);out.remove=removed end
    end
    return out
end
function M.apply(before,change)
    assert(type(change)=='table','Invalid execution delta')
    if change.set~=nil then
        for k in pairs(change)do assert(k=='set','Invalid execution replacement')end
        return M.clone(change.set)
    end
    local out=M.clone(before)
    if not next(change)then return out end
    assert(type(before)=='table' and before~=M.null,'Execution delta does not match its base value')
    if is_array(before) then
        for k in pairs(change)do assert(k=='entries' or k=='length','Invalid execution array delta')end
        local length=change.length or #before
        assert(type(length)=='number' and length>=0 and length==math.floor(length),'Invalid execution array length')
        local entries=change.entries or {}
        for i=#before+1,length do
            local entry=entries[tostring(i-1)]
            assert(entry and entry.set~=nil,'Execution delta leaves an unknown array entry')
        end
        for i=#out,length+1,-1 do out[i]=nil end
        for key,patch in pairs(entries)do
            local i=tonumber(key)
            assert(i and tostring(i)==key and i>=0 and i<length and i==math.floor(i),'Invalid execution array index')
            out[i+1]=M.apply(out[i+1],patch)
        end
    else
        for k in pairs(change)do assert(k=='fields' or k=='remove','Invalid execution object delta')end
        for _,k in ipairs(change.remove or {})do
            assert(out[k]~=nil,'Execution delta removes an absent field');out[k]=nil
        end
        for k,patch in pairs(change.fields or {})do
            assert(out[k]~=nil or patch.set~=nil,'Execution delta patches an absent field')
            out[k]=M.apply(out[k],patch)
        end
    end
    return out
end
function M.observe(record,id,view,base)
    local previous=record.snapshot
    local revision=(record.view_revision or 0)+1
    local out={view_ref={dispatch_id=id,revision=revision}}
    if previous and base and base.dispatch_id==id and base.revision==record.view_revision then
        out.view_delta={base=M.clone(base),change=M.delta(previous,view)}
    else out.view=view end
    record.snapshot=view;record.view_revision=revision
    return out
end
function M.checkpoint(record,request)
    if request.workflow_delta then
        local patch=request.workflow_delta
        assert(patch.base==record.workflow_revision,'Checkpoint base mismatch; no input was sent')
        return M.apply(record.workflow,patch.change)
    end
    assert(type(request.workflow)=='table','Missing workflow checkpoint')
    return M.clone(request.workflow)
end
function M.receipt_view(record,id,request)
    if request.view_ref then
        local ref=request.view_ref
        assert(ref.dispatch_id==id and ref.revision==record.view_revision and record.snapshot,
            'Final observation reference mismatch')
        return M.clone(record.snapshot)
    end
    return request.view and M.clone(request.view)
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
