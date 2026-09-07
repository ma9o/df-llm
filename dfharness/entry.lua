--@ module=true
--luacheck: globals request
-- DFHack owns source discovery, compilation and mtime invalidation. Each call
-- constructs fresh readers; native pointers never live in the script environment.
local assets={bridge='bridge',glyph='cp437',interactions='interactions',ui='native_ui',
    guard='input_guard',runtime='runtime',reports='reports',environment='environment',
    movement='movement',wire='wire',session='session',screen='screen',items='items',
    rest='rest',aim='aim',saving='saving',health='health',progress='progress',attack='attack',burden='burden',pathing='pathing'}

function request(payload)
    dfhack.df_llm_json_null=dfhack.df_llm_json_null or {}
    local null=dfhack.df_llm_json_null
    local req=require('json.internal'):new{strictTypes=true}:decode(payload,nil,{null=null})
    local modules={}
    local function include(key,name)
        local factory=dfhack.reqscript('dfharness/'..name).factory
        assert(type(factory)=='function','DF-LLM module has no factory: '..name)
        modules[key]=factory
    end
    for key,name in pairs(assets)do include(key,name)end
    if req.op=='character_status' or req.op=='character_brief' then
        include('character','character');include('details','character_details')
    elseif req.character_progress then
        include('character','character')
    end
    if (req.op=='poll' and req.observe) or req.op=='character_status' or req.op=='character_brief'
        or req.op=='observe' or req.op=='act' or req.op=='begin_dispatch' or req.op=='items'
        or req.op=='item' or req.op=='inspect' or req.op=='capabilities' then
        include('calculations','character_calculations')
    end
    if req.op=='unit' then include('unit','unit')end
    local result=modules.bridge(req,modules)
    print('__DFLLM_JSON__'..require('json').encode(result,{pretty=false,null=null}))
end
