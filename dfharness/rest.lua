--@ module=true
--luacheck: globals factory
local function build(...)
-- Native sleep/wait settings. Only native inputs change them; reads are pure.
local h=...
local M={}
local controls={
    {'sleep','A_SLEEP_SLEEP','Sleep as necessary'},
    {'wait','A_SLEEP_WAIT','Wait awake'},
    {'dawn','A_SLEEP_DAWN','Toggle until dawn'},
    {'less','ADVENTURE_LIST_SCROLL_UP','One hour less'},
    {'more','ADVENTURE_LIST_SCROLL_DOWN','One hour more'},
    {'page_less','ADVENTURE_LIST_SCROLL_PAGEUP','Four hours less'},
    {'page_more','ADVENTURE_LIST_SCROLL_PAGEDOWN','Four hours more'},
    {'confirm','SELECT','Begin the configured rest'},
    {'cancel','LEAVESCREEN','Cancel'},
}
function M.dawn(s)
    local out={available=false}
    local ok,err=pcall(function()
        assert(h.bindings.support().native_hotkey_available,'Native dawn model is unverified for this build')
        assert(df.game_type[df.global.gametype]=='ADVENTURE_MAIN','Native dawn model requires the main adventure mode')
        local tick,season=df.global.cur_year_tick,df.global.cur_season_tick
        local width=df.global.world.world_data.world_width
        local function integer(v,low,high)
            return type(v)=='number' and v==math.floor(v) and v>=low and v<=high
        end
        assert(integer(tick,0,403199) and integer(season,0,10079) and integer(width,1,32767),
            'Native dawn clock inputs are unavailable')
        assert(s and s.mode=='adventure' and s.year_tick==tick,'Native dawn snapshot is unavailable')
        local x
        if s.travel and s.travel.active then
            if s.travel.position then x=s.travel.position.x/48 end
        elseif s.position and s.map_origin then
            x=(s.position.x+s.map_origin.x)/768
        end
        assert(type(x)=='number' and x>=0 and x<width,'Native dawn longitude is unavailable')
        x=math.floor(x)
        -- Installed native clock 0x82def0; until-dawn completion at 0x11fcba
        -- compares phase 506. A start at that phase skips to the next dawn.
        -- Arena time uses another native clock and is deliberately unsupported.
        local phase=(tick+(season-math.floor(tick/10)+120)*10+x-math.floor(width/2))%1200*2
        local remaining=math.floor((506-phase)%2400/2)
        if remaining==0 then remaining=1200 end
        out={available=true,phase=phase,dawn_phase=506,world_region_x=x,
            remaining_calendar_ticks=remaining,source='df53.16-win-native-dawn-v1'}
    end)
    if not ok then out.reason=tostring(err):sub(1,240) end
    return out
end
function M.state(s)
    local out={available=true}
    local ok,err=pcall(function()
        local a=df.global.adventure
        for _,k in ipairs({'sleep_hours','sleeping','sleep_interrupt'}) do
            assert(type(a[k])=='number','Native rest field unavailable: '..k)
            out[k]=a[k]
        end
        for _,k in ipairs({'sleep_sleep','sleep_until_dawn','sleeping_indoors','sleeping_underground'}) do
            assert(type(a[k])=='boolean','Native rest field unavailable: '..k)
            out[k]=a[k]
        end
        if h.bindings.support().native_hotkey_available then
            out.model={hours_min=1,hours_max=24,page_hours=4,calendar_ticks_per_hour=50,
                calendar_ticks_per_year=403200}
        end
    end)
    if not ok then out.available=false;out.reason=tostring(err):sub(1,240) end
    if s then out.dawn=M.dawn(s) end
    return out
end
function M.open()
    local ok,open=pcall(function()return df.global.game.main_interface.adventure.sleep.open end)
    return ok and open==true
end
function M.menu()
    if not M.open() then return nil end
    local out={kind='rest',open=true,options=h.array(),settings=M.state()}
    local panel=df.global.game.main_interface.adventure.sleep
    out.no_sky=panel.no_sky
    if not out.settings.available or type(out.no_sky)~='boolean' then
        out.selection_unavailable=out.settings.reason or 'Native sky visibility is unavailable'
        return out
    end
    for i,c in ipairs(controls) do
        if c[1]~='dawn' or not out.no_sky then
            local option=h.bindings.fixed({id='rest:'..c[1],index=i-1,
                kind='rest_control',native_type=c[1],label=c[3]},c[2],out.settings.model~=nil)
            out.options[#out.options+1]=option
            if not option.selection then out.selection_unavailable='No verified native rest control for this build' end
        end
    end
    return h.bindings.catalog(out)
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
