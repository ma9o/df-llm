--@ module=true
--luacheck: globals factory
local function build()
-- Deterministic input-state identity, independent of incidental rendered text
-- when every open interface has a native structured guard.
local json=require('json')
local function canonical(value)
    if type(value)~='table' then return json.encode(value,{pretty=false}) end
    local entries={}
    for k,v in pairs(value) do
        entries[#entries+1]={key=type(k)..':'..tostring(k),value=v}
    end
    table.sort(entries,function(a,b)return a.key<b.key end)
    local out={}
    for _,entry in ipairs(entries) do
        out[#out+1]=json.encode(entry.key)..':'..canonical(entry.value)
    end
    return '{'..table.concat(out,',')..'}'
end
return function(s,ui,native,effects_only)
    local payload={schema=2,native=native}
    for _,k in ipairs({'screen','focus','world_frame','year','year_tick','save','turn_phase',
        'adventurer_id','adventure_menu','open_panels','position','map_origin','viewport','travel',
        'modal','processing','ready_for_input','map_loaded','mode','interface_unavailable','world_epoch','local_map_epoch'}) do payload[k]=s[k] end
    payload.dimensions={width=ui.width,height=ui.height}
    if s.modal and s.modal.kind=='help' and type(s.modal.text)=='table' then
        -- DF lays out native help words after opening the panel. Line breaks
        -- can change on the next render without changing the delegated prompt.
        -- Keep every word and the title/button guarded, independent of wrapping.
        local modal={}
        for k,v in pairs(s.modal) do modal[k]=v end
        modal.text=table.concat(s.modal.text,' '):gsub('%s+',' '):match('^%s*(.-)%s*$')
        payload.modal=modal
    end
    if not effects_only then payload.action_serial=s.action_serial end
    -- Text remains a conservative fallback for undecoded screens/decisions.
    -- Explicit raw clicks/text are also resolved against their live UI by act.
    if not native.complete then payload.ui=ui.rows end
    return 'n2:'..dfhack.internal.md5(canonical(payload))
end

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
