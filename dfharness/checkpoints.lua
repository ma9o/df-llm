--@ module=true
--luacheck: globals factory
local function build(...)
-- Save-scoped session index. Durable only when DF saves the game. Entries use
-- fixed slots so retention is bounded; full observations stay in JSONL/session RAM.
local wire=...
local M={}
local KEY='df-llm/session/v1/'
local LIMIT,BYTES=128,131072
local function decode(body,limit)
    assert(type(body)=='string' and #body<=limit,'Invalid or oversized saved checkpoint')
    -- getWorldData's default decoder does not preserve all JSON types. Store a
    -- JSON string and decode it strictly, preserving null/empty arrays/objects.
    local value=require('json.internal'):new{strictTypes=true}:decode(body,nil,{null=wire.null})
    assert(type(value)=='table' and value.schema_version==1,'Unsupported checkpoint schema')
    return value
end
local function save(key,value,limit)
    local body=wire.encode(value)
    assert(#body<=limit,'Saved checkpoint exceeds its byte limit')
    dfhack.persistent.saveWorldData(KEY..key,body)
end
local function failed(state,err)
    state.available=false;state.reason=tostring(err):sub(1,240)
end
function M.open(session)
    if session.persistence then return session.persistence end
    local state={available=false,index={schema_version=1,next_slot=0,entries={}},restore={}}
    session.persistence=state
    local ok,err=pcall(function()
        assert(dfhack.isWorldLoaded(),'No world loaded')
        assert(type(dfhack.persistent.getWorldData)=='function' and type(dfhack.persistent.saveWorldData)=='function',
            'DFHack persistent world storage is unavailable')
        local body=dfhack.persistent.getWorldData(KEY..'index')
        if body then
            state.index=decode(body,65536)
            local index=state.index
            assert(type(index.next_slot)=='number' and index.next_slot>=0 and index.next_slot<LIMIT
                and index.next_slot%1==0 and type(index.entries)=='table','Invalid saved session index')
            local count=0
            for slot,entry in pairs(index.entries)do
                local number=tonumber(slot)
                assert(number and number>=0 and number<LIMIT and tostring(number)==slot,'Invalid checkpoint slot')
                assert(type(entry.id)=='string' and #entry.id<=100,'Invalid saved dispatch ID')
                assert(not state.restore[entry.id],'Duplicate saved dispatch identity')
                count=count+1;assert(count<=LIMIT,'Saved session index exceeded retention')
                state.restore[entry.id]=slot
                -- Loading an older save must replace newer RAM progress with
                -- what was actually stored in that save, including diagnostics.
                session.dispatches[entry.id]=nil
            end
        end
        state.available=true
    end)
    if not ok then failed(state,err)end
    return state
end
function M.lookup(session,id)
    local state=M.open(session)
    if not state.available then return session.dispatches[id]end
    local slot=state.restore[id]
    if not slot then return session.dispatches[id]end
    state.restore[id]=nil
    local meta=state.index.entries[slot]
    local ok,record=pcall(function()
        local r=decode(dfhack.persistent.getWorldData(KEY..slot),BYTES)
        assert(r.id==id,'Saved checkpoint identity mismatch')
        r.restored_epoch=session.world_epoch
        r.resumed_by=meta.resumed_by
        return r
    end)
    if not ok then
        record={restored_epoch=session.world_epoch,restore_reason=tostring(record):sub(1,240)}
        meta.resumable=false;meta.reason=record.restore_reason
    end
    session.dispatches[id]=record
    session.dispatch_order=session.dispatch_order or {}
    for i=#session.dispatch_order,1,-1 do
        if session.dispatch_order[i]==id then table.remove(session.dispatch_order,i)end
    end
    session.dispatch_order[#session.dispatch_order+1]=id
    if #session.dispatch_order>LIMIT then session.dispatches[table.remove(session.dispatch_order,1)]=nil end
    return record
end
local function slot_for(state,id)
    for slot,entry in pairs(state.index.entries)do if entry.id==id then return slot end end
end
function M.begin(session,id,record,resume_id)
    local state=M.open(session)
    -- A missing API disables persistence explicitly. The caller must block a
    -- saved resume if it cannot invalidate that predecessor's lease first.
    if not state.available then return false,state.reason end
    local ok,err=pcall(function()
        local slot=tostring(state.index.next_slot)
        local expired=state.index.entries[slot]
        if expired then state.restore[expired.id]=nil end
        state.index.next_slot=(state.index.next_slot+1)%LIMIT
        state.index.entries[slot]={id=id,action=record.workflow.action.type,outcome='in_progress',
            resumable=false,reason='Dispatch has no settled checkpoint'}
        if resume_id then
            local old=slot_for(state,resume_id)
            if old then state.index.entries[old].resumed_by=id end
        end
        -- Mark the lease before any native input can run or any game save can
        -- persist it. A crash in the middle is diagnostic, never a replay lease.
        save(slot,{schema_version=1,id=id,request=record.request,adventurer_id=record.adventurer_id,
            restore_reason='Dispatch was active when the game was saved; native input delivery cannot be recovered'},BYTES)
        save('index',state.index,65536)
    end)
    if not ok then failed(state,err)end
    return ok,state.reason
end
local function boundary(record,view,receipt)
    if record.dispatch.outcome=='completed' then return nil,'Dispatch already completed' end
    if not view or not view.checkpoint_guard then return nil,'Native state is not a settled local checkpoint' end
    if receipt and (not receipt.settled or receipt.error)then return nil,'Native input has not settled successfully' end
    local workflow=record.workflow
    local ctx=workflow.context or {}
    if ctx.stages then
        local index=ctx.stage_index
        if type(index)~='number' or index%1~=0 or index<0 or index>=#ctx.stages then
            return nil,'No unfinished stage at this checkpoint'
        end
        if #ctx.results~=index then return nil,'Completed stage receipts do not match progress' end
        for _,result in ipairs(ctx.results)do
            if result.outcome~='completed' then return nil,'A preceding stage is not verified complete' end
        end
        ctx=ctx.stages[index+1].context or {}
    end
    -- Recipe-local pending markers and state IDs are not portable. Preserve the
    -- workflow for diagnosis, but re-enable execution only before a fresh stage.
    if next(ctx) then return nil,'Current stage has mechanical progress; only verified stage boundaries survive reload' end
    return view.checkpoint_guard
end
function M.finish(session,id,record,view,receipt)
    local state=M.open(session)
    if not state.available then return false,state.reason end
    local ok,err=pcall(function()
        local slot=assert(slot_for(state,id),'Dispatch is not in the saved session index')
        local guard,reason=boundary(record,view,receipt)
        local saved={schema_version=1,id=id,request=record.request,workflow=record.workflow,
            dispatch=record.dispatch,compact=record.compact,save=record.save,
            adventurer_id=record.adventurer_id,resume_guard=guard,restore_reason=reason}
        if #wire.encode(saved)>BYTES then
            saved.workflow=nil;saved.dispatch=nil;saved.compact=nil;saved.resume_guard=nil
            saved.restore_reason='Dispatch exceeds saved checkpoint byte limit; full trace remains in session/JSONL'
        end
        local entry=state.index.entries[slot]
        entry.outcome=record.dispatch.outcome;entry.resumable=saved.resume_guard~=nil;entry.reason=saved.restore_reason
        save(slot,saved,BYTES);save('index',state.index,65536)
        record.persistent_resume_guard=saved.resume_guard
    end)
    if not ok then failed(state,err)end
    return ok,state.reason
end
function M.describe(session,limit)
    local state=M.open(session)
    local out={available=state.available,reason=state.reason,retention=LIMIT,record_byte_limit=BYTES,
        storage='dfhack.persistent world data; written to disk with the next game save',
        resume='Explicit resume at a verified fresh stage, with matching saved native state; choices are always revoked',
        dispatches=require('json.internal'):newArray{}}
    out.total=0;for _ in pairs(state.index.entries)do out.total=out.total+1 end
    for offset=1,LIMIT do
        local entry=state.index.entries[tostring((state.index.next_slot-offset)%LIMIT)]
        if entry then
            out.dispatches[#out.dispatches+1]=wire.clone(entry)
            if #out.dispatches>=limit then break end
        end
    end
    out.truncated=#out.dispatches<out.total
    return out
end
return M
end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
